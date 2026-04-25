"""V4 Pro-distillation pass.

Reads the CLEANED situations from build_v4_situations.py and sends each
one to Gemini 3.1 Pro with the full Master Playbook as system
instruction. Pro produces a new strategically-correct Alex-voice label
for every situation. Those (situation → Pro label) pairs become the v4
training dataset.

Key difference from the original distill_from_pro.py:
  • Reads structured list-of-message context (not a pre-flattened string)
  • Output preserves the full original row + adds a ``pro_reply`` field
  • Stronger quality filter on Pro outputs (drop leaks, drop echoes)

Async + parallel with concurrency 6, timeout 30s, key rotation, and
incremental save so a crash doesn't waste API spend. Resume support
means rerunning picks up where it left off.
"""

from __future__ import annotations

import asyncio
import json
import re
import random
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from wingman.config import PRO_MODEL, _ALL_KEYS, permissive_safety_settings
from google import genai
from google.genai import types as gtypes


IN_FILE = Path(__file__).parent.parent / "training_dataset" / "v4_situations.jsonl"
OUT_FILE = Path(__file__).parent.parent / "training_dataset" / "v4_pro_pairs.jsonl"


# Prompt we send to Pro. The playbook is in the system instruction;
# the user turn is a minimal "here's the conversation, tell me what
# Alex would reply." Pro outputs ONLY the reply, no JSON.
DISTILL_USER_PROMPT = (
    "Conversation so far:\n{transcript}\n\n"
    "Write the single best next reply in Alex's voice. Short natural "
    "SMS. Strategically correct for THIS specific moment in the chat "
    "— use the playbook's frameworks. Output ONLY the reply text, no "
    "quotes, no JSON, no preamble."
)


# Quality filter for Pro outputs. Same spirit as the tuned-model
# output validator.
_SPEAKER_PREFIX = re.compile(r"^\s*(her|them|me|alex|girl)\s*[:\-]", re.I)
_SYS_LEAK_TOKENS = (
    "you are alex", "playing with fire", "text-game coach",
    "output only", "respond with one short",
)


def _pro_reply_ok(reply: str) -> bool:
    r = reply.strip()
    if len(r) < 5 or len(r) > 500:
        return False
    if _SPEAKER_PREFIX.match(r):
        return False
    low = r.lower()
    return not any(tok in low for tok in _SYS_LEAK_TOKENS)


def _format_transcript(ctx_messages: list[dict]) -> str:
    lines = []
    for m in ctx_messages:
        tag = "ME" if m.get("speaker") == "me" else "HER"
        text = (m.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"{tag}: {text}")
    return "\n".join(lines)


async def _call_pro(
    client: genai.Client,
    ctx_messages: list[dict],
    system_instruction: str,
    timeout_s: float = 30.0,
) -> tuple[str, str | None]:
    """One Pro call. Returns (reply, error_str|None). Streaming so we
    can enforce per-request timeout that kills hung connections."""
    transcript = _format_transcript(ctx_messages)
    prompt = DISTILL_USER_PROMPT.format(transcript=transcript)
    config = gtypes.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.85,
        max_output_tokens=6144,
        safety_settings=permissive_safety_settings(),
    )
    accumulated = ""
    try:
        async def _consume():
            nonlocal accumulated
            stream = await client.aio.models.generate_content_stream(
                model=PRO_MODEL, contents=prompt, config=config,
            )
            async for chunk in stream:
                if chunk.text:
                    accumulated += chunk.text
        await asyncio.wait_for(_consume(), timeout=timeout_s)
        reply = accumulated.strip().strip('"').strip("'").strip()
        return reply, None
    except asyncio.TimeoutError:
        return "", f"timeout>{timeout_s}s"
    except Exception as exc:
        return "", str(exc)[:160]


async def distill(concurrency: int = 6, per_request_timeout: float = 30.0,
                   shuffle_seed: int = 42):
    if not IN_FILE.exists():
        print(f"[v4-distill] ERROR: {IN_FILE} not found — run "
              f"build_v4_situations first.", file=sys.stderr)
        sys.exit(1)

    # Load playbook for system instruction — same as Pro sees in prod
    from wingman.training_rag import TrainingRAG
    rag = TrainingRAG()
    rag.load()
    playbook = rag.knowledge_summary or ""
    persona = (
        "You are Alex, a high-value dating text-game coach in the voice "
        "of Playing With Fire. Read the chat and respond with ONE short, "
        "natural, witty, specific SMS reply in Alex's voice. Output ONLY "
        "the reply text."
    )
    system_instruction = f"{persona}\n\n{playbook}".strip()
    print(f"[v4-distill] System instruction: {len(system_instruction):,} chars "
          f"(persona + {len(playbook):,} chars playbook)")

    # Load situations
    situations: list[dict] = []
    with IN_FILE.open() as f:
        for line in f:
            try:
                situations.append(json.loads(line))
            except Exception:
                continue
    print(f"[v4-distill] {len(situations)} situations to label")

    # Resume support — key by serialized context so re-runs skip done rows
    done_keys: set[str] = set()
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    if OUT_FILE.exists():
        with OUT_FILE.open() as f:
            for line in f:
                try:
                    d = json.loads(line)
                    key = json.dumps(d.get("context_messages"), ensure_ascii=False)
                    done_keys.add(key)
                except Exception:
                    pass
        print(f"[v4-distill] Resume: {len(done_keys)} already done, "
              f"{len(situations) - len(done_keys)} to go")
    remaining = [
        s for s in situations
        if json.dumps(s.get("context_messages"), ensure_ascii=False) not in done_keys
    ]
    if not remaining:
        print("[v4-distill] Nothing to do.")
        return OUT_FILE

    random.Random(shuffle_seed).shuffle(remaining)

    # Per-key client pool (round-robin). Key rotation on failure.
    clients = [genai.Client(api_key=k) for k in _ALL_KEYS]
    print(f"[v4-distill] {len(clients)} API keys, concurrency={concurrency}, "
          f"per_call_timeout={per_request_timeout}s")

    sem = asyncio.Semaphore(concurrency)
    out_lock = asyncio.Lock()
    stats = {
        "ok": 0, "failed": 0, "filtered": 0,
        "started": time.time(),
    }

    async def worker(i: int, item: dict):
        client = clients[i % len(clients)]
        async with sem:
            for attempt in range(3):
                reply, err = await _call_pro(
                    client, item["context_messages"],
                    system_instruction, per_request_timeout,
                )
                if reply and _pro_reply_ok(reply):
                    async with out_lock:
                        with OUT_FILE.open("a", encoding="utf-8") as f:
                            row = dict(item)
                            row["pro_reply"] = reply
                            f.write(json.dumps(row, ensure_ascii=False) + "\n")
                        stats["ok"] += 1
                        if stats["ok"] % 50 == 0:
                            elapsed = time.time() - stats["started"]
                            rate = stats["ok"] / max(1, elapsed)
                            remaining_count = len(remaining) - stats["ok"]
                            eta = remaining_count / max(0.1, rate)
                            print(f"[v4-distill]   {stats['ok']}/{len(remaining)} "
                                  f"({rate:.2f}/s, ETA {eta/60:.1f}min)")
                    return
                # Classify error
                if reply and not _pro_reply_ok(reply):
                    async with out_lock:
                        stats["filtered"] += 1
                    return  # keep the bad reply out; don't retry
                is_rate = "429" in (err or "") or "RESOURCE_EXHAUSTED" in (err or "")
                is_overload = ("503" in (err or "") or "UNAVAILABLE" in (err or "")
                               or "timeout" in (err or "").lower())
                if is_rate or is_overload:
                    client = clients[(i + attempt + 1) % len(clients)]
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                break
            async with out_lock:
                stats["failed"] += 1
                print(f"[v4-distill]   FAIL ({item.get('source','?')}): {err}")

    tasks = [worker(i, item) for i, item in enumerate(remaining)]
    await asyncio.gather(*tasks)

    elapsed = time.time() - stats["started"]
    print()
    print("=" * 60)
    print("V4 PRO DISTILLATION COMPLETE")
    print(f"  OK:        {stats['ok']}")
    print(f"  Filtered:  {stats['filtered']} (Pro output rejected by quality filter)")
    print(f"  Failed:    {stats['failed']}")
    print(f"  Elapsed:   {elapsed/60:.1f} min")
    print(f"  Output:    {OUT_FILE}")
    print("=" * 60)
    return OUT_FILE


def main():
    asyncio.run(distill())


if __name__ == "__main__":
    main()
