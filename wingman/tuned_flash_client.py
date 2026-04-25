"""Vertex-hosted tuned Gemini 2.5 Flash — reply generation client.

Talks to the fine-tuned endpoint that ``wingman.run_finetune`` produced
via teacher-student distillation (Gemini 3.1 Pro labels → 2.5 Flash
weights).

CRITICAL: The tuned model was trained on a very specific prompt shape —
minimal system instruction + "Conversation so far:\n...\nWrite the next
reply" → single-line reply output. If we send it our normal 13k-char
system prompt with the "Format as JSON with 5 replies" instruction, it
falls out of distribution and returns empty. So this client rebuilds
the prompt to match training + calls the model 5x in parallel with
temperature variation to produce 5 diverse replies → wrapped as JSON
for the standard Wingman UI.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Awaitable, Callable


PROJECT = "nicheflix-cd240"
LOCATION = "us-central1"

# Tuned model endpoints — we keep v1, v2, v3 all registered so the UI
# can flip between them for A/B testing without redeploying anything.
# The "active version" is a runtime setting (wingman.tuned_version),
# but we always fall back to whatever TUNED_VERSION env var says.
JOB_CONFIG_PATH = Path(__file__).parent.parent / "training_dataset" / "vertex_job.json"

# Runtime override for the active version — set via WS action
# ``set_tuned_version``. None = use the env default.
_active_version: str | None = None


def set_active_version(version: str) -> None:
    """Flip the active tuned-model version without restarting. Called
    from the UI via a WS action. Accepts v1 / v2 / v3 / v4."""
    global _active_version
    v = (version or "").strip().lower()
    if v in ("v1", "v2", "v3", "v4"):
        _active_version = v


def get_active_version() -> str:
    """Return whichever version is currently active (runtime override
    > env default > legacy single endpoint > v4)."""
    if _active_version:
        return _active_version
    return (os.getenv("TUNED_VERSION") or "v4").strip().lower()


def get_tuned_endpoint(version: str | None = None) -> str:
    """Return the endpoint resource name for the given version. When
    ``version`` is None, uses the active runtime version."""
    v = (version or get_active_version()).lower()
    env_key = f"TUNED_{v.upper()}_ENDPOINT"
    env_val = (os.getenv(env_key) or "").strip()
    if env_val:
        return env_val
    # Legacy single-endpoint fallback — lets users who used the earlier
    # integration stay working without migrating their .env immediately.
    legacy = (os.getenv("TUNED_FLASH_ENDPOINT") or "").strip()
    if legacy:
        return legacy
    # Last resort: on-disk job config written by run_finetune poller
    if JOB_CONFIG_PATH.exists():
        try:
            d = json.loads(JOB_CONFIG_PATH.read_text())
            return (d.get("tuned_model_endpoint") or "").strip()
        except Exception:
            pass
    return ""


def get_available_versions() -> list[str]:
    """Return the list of versions that have an endpoint configured."""
    out = []
    for v in ("v1", "v2", "v3", "v4"):
        if (os.getenv(f"TUNED_{v.upper()}_ENDPOINT") or "").strip():
            out.append(v)
    return out


def is_tuned_configured() -> bool:
    return bool(get_tuned_endpoint())


# MATCHES training system instruction byte-for-byte. Don't change
# without retraining — the model learned to produce Alex-voice outputs
# keyed on THIS exact string.
TRAINING_SYSTEM_INSTRUCTION = (
    "You are Alex, a high-value dating text-game coach in the voice of "
    "Playing With Fire. Read the conversation and respond with ONE short "
    "natural SMS reply — witty, specific, punchy, emotionally aware, "
    "never generic. Output ONLY the reply text."
)


def _build_inference_system_instruction() -> str:
    """Inference-time system prompt. Style is in weights (from fine-
    tuning). But the model also needs STRATEGIC guidance — when to
    takeaway, withdrawal plays, shit-test handling, logistics pivots,
    etc. Pro gets this from the Master Playbook at inference; the
    tuned model was losing it because we stripped context to make it
    fast. Re-inject the playbook here — small cost (+9k tokens), huge
    strategic lift on situations where voice alone isn't enough."""
    parts = [TRAINING_SYSTEM_INSTRUCTION]
    try:
        playbook_path = Path(__file__).parent.parent / "training" / ".master_playbook.json"
        if playbook_path.exists():
            pb = json.loads(playbook_path.read_text())
            pb_text = pb.get("playbook") or ""
            if pb_text:
                parts.append(pb_text)
    except Exception:
        pass
    return "\n\n".join(parts)


# Build once at import so every call reuses the cached string.
INFERENCE_SYSTEM_INSTRUCTION = _build_inference_system_instruction()


def _msg_field(m, key: str, default: str = "") -> str:
    """Dict-or-dataclass field reader (mirrors other modules)."""
    if hasattr(m, key):
        return getattr(m, key) or default
    if isinstance(m, dict):
        return m.get(key, default) or default
    return default


def _format_transcript(messages, max_msgs: int = 60) -> str:
    """Render messages as 'HER:/ME:' lines matching training format.

    v3 models are trained with up to ``MAX_CONTEXT_MSGS=60`` prior
    messages per example, so at inference we pass the same window.
    Chats shorter than the cap get sent in full — the model handles
    short contexts because v3 training included early-arc examples
    with 2-5 messages of context.
    """
    recent = messages[-max_msgs:] if len(messages) > max_msgs else messages
    lines = []
    for m in recent:
        speaker = _msg_field(m, "speaker")
        tag = "ME" if speaker == "me" else "HER"
        text = _msg_field(m, "text").strip()
        if not text:
            continue
        lines.append(f"{tag}: {text}")
    return "\n".join(lines)


# Five reply angles, BUT the angle hint is NO LONGER appended to the
# user prompt — v3 training didn't include any hint text, so sending
# it out-of-distribution occasionally caused the model to echo the
# system prompt or drift into the chat pattern instead of replying.
# We now use temperature variation ALONE for diversity, which stays
# fully in-distribution. The label/why are kept for UI display.
#
# Temperatures capped at 0.90 (was 1.0) — the Sexual angle at temp=1.0
# was the most common producer of OOD collapses in practice.
_REPLY_ANGLES = [
    ("Bold",     "Bold / takeaway / challenge-frame.",                         0.75),
    ("Playful",  "Playful / push-pull / callback banter.",                     0.85),
    ("Direct",   "Direct / move forward / propose logistics.",                 0.70),
    ("Sexual",   "Sexual tension / escalate innuendo.",                        0.90),
    ("Cerebral", "Witty / specific callback to something she said.",           0.80),
]


# Regex guards that strip problematic outputs entirely. Any reply that
# starts with a speaker label (HER:/ME:/THEM:/ALEX:) is the model
# continuing the chat pattern instead of giving us a reply — drop it.
# Any reply that contains system-prompt echoes is also dropped.
import re as _re
_SPEAKER_ECHO_RE = _re.compile(r"^\s*(her|them|me|alex|girl)\s*[:\-]", _re.IGNORECASE)
_SYS_LEAK_TOKENS = [
    "you are alex",
    "high-value dating",
    "text-game coach",
    "playing with fire",
    "output only the reply",
    "respond with one short",
]


def _reply_is_valid(text: str) -> tuple[bool, str]:
    """Returns (ok, reason_if_not). Filters model outputs that clearly
    collapsed out of distribution."""
    t = (text or "").strip()
    if len(t) < 3:
        return False, "too short"
    if len(t) > 600:
        return False, "too long"
    if _SPEAKER_ECHO_RE.match(t):
        return False, "speaker label prefix"
    low = t.lower()
    for tok in _SYS_LEAK_TOKENS:
        if tok in low:
            return False, f"system-prompt leak ({tok!r})"
    return True, ""


async def _single_tuned_call(
    client,
    endpoint: str,
    transcript: str,
    goal: str,
    extra_context: str,
    angle_hint: str,
    temperature: float,
    timeout_s: float,
):
    """One call to the tuned endpoint. Matches training prompt shape
    as closely as possible + appends a tiny angle hint for variety.

    TWO CRITICAL PERFORMANCE KNOBS:
      1. ``thinking_budget=0`` — Gemini 2.5 Flash has reasoning built in,
         and thinking tokens can eat the output budget before real text
         is generated (causing mid-sentence truncation like "choke on").
         Our style lives in the fine-tune weights, so there's nothing to
         "reason" about — disable thinking entirely.
      2. ``max_output_tokens=2048`` — generous headroom so the raw reply
         can never be truncated. Cheap (Flash output is $1.50/M) and
         eliminates the whole truncation class of failures.
    """
    from google.genai import types as gtypes

    # Prompt shape matches training EXACTLY — no hints, no extras in
    # the middle of the chat text. Anything new we add appears AFTER
    # the "Write the next reply..." line so the training prefix stays
    # byte-identical.
    user_text = (
        "Conversation so far:\n"
        f"{transcript}\n\n"
        "Write the next reply I should send."
    )
    if goal:
        user_text += f"\n\nMy goal for this chat: {goal}"
    if extra_context:
        user_text += f"\n\nExtra context: {extra_context}"
    # Angle hint removed — training prompts didn't contain one, and
    # adding it at inference caused occasional OOD collapses. Diversity
    # now comes entirely from temperature variation.
    _ = angle_hint  # kept in signature for API compatibility

    # Build config. Only attach thinking_config if the SDK version
    # supports it — older installs will skip that knob gracefully.
    config_kwargs = {
        # Use the AUGMENTED system instruction at inference (playbook
        # re-injected). Model still recognizes the training prefix
        # because TRAINING_SYSTEM_INSTRUCTION is the FIRST part of
        # INFERENCE_SYSTEM_INSTRUCTION, so voice-from-weights still
        # activates on the stable opening string.
        "system_instruction": INFERENCE_SYSTEM_INSTRUCTION,
        "temperature": temperature,
        "max_output_tokens": 2048,
    }
    try:
        config_kwargs["thinking_config"] = gtypes.ThinkingConfig(thinking_budget=0)
    except Exception:
        pass  # Older SDK — thinking is on by default, tolerate it
    config = gtypes.GenerateContentConfig(**config_kwargs)

    try:
        resp = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=endpoint, contents=user_text, config=config,
            ),
            timeout=timeout_s,
        )
        text = (resp.text or "").strip().strip('"').strip("'").strip()
        return text
    except asyncio.TimeoutError:
        print(f"[tuned] timeout ({angle_hint[:20]}) after {timeout_s}s")
        return ""
    except Exception as exc:
        print(f"[tuned] single call failed ({angle_hint[:20]}): "
              f"{str(exc)[:100]}")
        return ""


async def generate_tuned_replies_json(
    messages,
    goal: str = "",
    extra_context: str = "",
    on_chunk: Callable[[str], Awaitable[None]] | None = None,
    timeout_s: float = 30.0,
) -> str:
    """Generate 5 diverse reply options by calling the tuned model in
    parallel with temperature + angle variation. Returns a JSON string
    in Wingman's standard reply format so the downstream parser
    (``ReplyGenerator._parse_response``) consumes it unchanged."""
    endpoint = get_tuned_endpoint()
    if not endpoint:
        raise RuntimeError(
            "Tuned model not configured — train first or set "
            "TUNED_FLASH_ENDPOINT in .env"
        )

    from google import genai

    transcript = _format_transcript(messages)
    if not transcript:
        return ""

    client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)

    # Five parallel calls, hedged pattern:
    #   • Per-call timeout: 8s (hard kill)
    #   • As soon as 4 of 5 return → ship (cancel the straggler)
    #   • Otherwise: ship whatever we have at 8s hard deadline
    #
    # The hedge is the key fix: ONE slow shard shouldn't gate the UI.
    # Getting 4 good replies in 3s beats waiting 12s for the 5th one.
    PER_CALL_TIMEOUT = min(timeout_s, 8.0)
    OVERALL_DEADLINE = min(timeout_s, 8.0)
    SHIP_WITH = 4  # ship when we have this many, don't wait for 5th

    print(f"[tuned] Firing 5 parallel calls to {endpoint.split('/')[-1]} "
          f"(ship with ≥{SHIP_WITH}, deadline {OVERALL_DEADLINE}s)...")

    import time as _time
    t0 = _time.time()
    tasks = [
        asyncio.create_task(_single_tuned_call(
            client, endpoint, transcript, goal, extra_context,
            angle_hint=hint, temperature=temp, timeout_s=PER_CALL_TIMEOUT,
        ))
        for (_, hint, temp) in _REPLY_ANGLES
    ]

    # Collect completions one at a time until we have enough OR we
    # blow the overall deadline.
    ok_count = 0
    pending: set = set(tasks)
    while pending:
        remaining_budget = OVERALL_DEADLINE - (_time.time() - t0)
        if remaining_budget <= 0:
            break
        done_now, pending = await asyncio.wait(
            pending, timeout=remaining_budget,
            return_when=asyncio.FIRST_COMPLETED,
        )
        # Count successful replies in this batch
        for t in done_now:
            if (not t.cancelled() and not t.exception()
                    and (t.result() or "").strip()):
                ok_count += 1
        # Ship early once we have enough good replies
        if ok_count >= SHIP_WITH:
            break

    # Cancel anything still running — they'd just waste tokens
    cancelled_count = len(pending)
    for t in pending:
        t.cancel()

    # Collect results in original order so the angle labels match
    raw_replies: list[str] = []
    for task in tasks:
        if task.done() and not task.cancelled() and not task.exception():
            raw_replies.append(task.result() or "")
        else:
            raw_replies.append("")

    # Validate + dedupe. Invalid = speaker-label echo, system-prompt
    # leak, too short/long. Dropped silently so the UI only sees the
    # good ones. Dedupe happens on a normalized form of the reply text.
    replies: list[dict] = []
    seen: set[str] = set()
    dropped = 0
    for (label, hint, _temp), text in zip(_REPLY_ANGLES, raw_replies):
        if not text:
            continue
        ok, reason = _reply_is_valid(text)
        if not ok:
            dropped += 1
            print(f"[tuned] dropped {label}: {reason} — {text[:60]!r}")
            continue
        # Normalize for dedup: lowercase, strip punctuation, collapse ws
        key = "".join(c for c in text.lower() if c.isalnum() or c.isspace())
        key = " ".join(key.split())[:80]
        if key in seen:
            continue
        seen.add(key)
        replies.append({
            "label": label,
            "text": text,
            "why": hint,
        })
    if dropped:
        print(f"[tuned] {dropped} raw replies rejected by validator")

    total_elapsed = _time.time() - t0
    if not replies:
        print(f"[tuned] All 5 parallel calls returned empty "
              f"({total_elapsed:.1f}s elapsed)")
        return ""

    print(f"[tuned] Got {len(replies)}/5 unique replies in "
          f"{total_elapsed:.1f}s"
          + (f" (cancelled {cancelled_count} stragglers)" if cancelled_count else ""))

    result = {
        "read": "",
        "advice": "",
        "replies": replies,
    }
    out = json.dumps(result, ensure_ascii=False)
    # Fake "stream complete" signal so the UI shows replies the moment
    # we return. The frontend already renders on each chunk callback.
    if on_chunk:
        try:
            await on_chunk(out)
        except Exception:
            pass
    return out


# Keep the old name as an alias so the existing route in
# wingman/reply_generator.py still imports it cleanly. This is the
# function used as the Tuned model's generate_stream equivalent.
async def generate_tuned_stream(
    system_instruction: str,   # ignored — we use the training instruction
    user_text: str,            # ignored — we rebuild from messages
    images: list[bytes] | None = None,   # ignored — model was trained text-only
    on_chunk: Callable[[str], Awaitable[None]] | None = None,
    temperature: float = 0.9,
    max_tokens: int = 8192,
    timeout_s: float = 30.0,
    _messages=None,
    _goal: str = "",
    _extra_context: str = "",
) -> str:
    """Backward-compat wrapper. The existing generator call site passes
    system_instruction + user_text; we IGNORE those (they're out-of-
    distribution for the tuned model) and instead rebuild from the raw
    messages passed via the ``_messages`` kwarg. See _generate_replies
    in wingman/main.py for the call site."""
    if _messages is None:
        raise RuntimeError(
            "generate_tuned_stream needs _messages (raw chat messages). "
            "Caller must pass them — system_instruction/user_text are "
            "ignored for the tuned model."
        )
    return await generate_tuned_replies_json(
        _messages, goal=_goal, extra_context=_extra_context,
        on_chunk=on_chunk, timeout_s=timeout_s,
    )
