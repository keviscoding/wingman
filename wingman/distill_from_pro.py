"""Teacher-student distillation: Gemini 3.1 Pro generates the training
labels for Gemini 2.5 Flash.

For each situation in the Examples Library, we ask Gemini 3.1 Pro
(with the Master Playbook in its system instruction, matching how it
runs in production) to produce the single best Alex-voice reply. Those
Pro outputs become the training labels for a new supervised fine-tune
of 2.5 Flash.

Why this is different from training on the user's own replies:
  • User replies teach Flash to mimic the USER's style.
  • Pro replies teach Flash to mimic PRO's reasoning + quality.
  • The user asked for the latter — they want Pro-level output speed
    at Flash's price / latency.

Design choices:
  • Parallel with a Semaphore cap so we don't get rate-limited.
  • Per-request timeout (30s) so stuck streams don't poison throughput.
  • Rotate API key on 429 / hang.
  • Incremental save — every completed pair is flushed to disk so a
    crash doesn't waste API spend.
  • Resume support — if output file exists, skip situations already
    labeled.
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from wingman.config import (
    PRO_MODEL, _ALL_KEYS, rotate_api_key,
    permissive_safety_settings,
)
from google import genai
from google.genai import types as gtypes


EXAMPLES_FILE = Path(__file__).parent.parent / "examples_library" / ".examples.json"
OUT_DIR = Path(__file__).parent.parent / "training_dataset"
PAIRS_FILE = OUT_DIR / "pro_distillation_pairs.jsonl"

# Same filter as build_finetune_dataset so the two agree on what's
# "good enough to train on".
MIN_SITUATION_CHARS = 40
MIN_REPLY_CHARS = 5
MAX_REPLY_CHARS = 500
MAX_SITUATION_CHARS = 3000


# Distillation prompt for the TEACHER (Pro). We load the Master
# Playbook into the system instruction exactly like the production
# pipeline — it sharpens Pro's output and keeps the same distribution
# the app actually produces day-to-day.
DISTILL_USER_PROMPT = (
    "Conversation so far:\n{situation}\n\n"
    "Write exactly ONE short natural SMS reply I should send — in "
    "Alex's voice. Output ONLY the reply text. No JSON. No quotes. "
    "No preamble. Just the reply, ready to paste into the chat."
)


def _clean_situation(text: str) -> str:
    t = (text or "").strip()
    if len(t) > MAX_SITUATION_CHARS:
        t = t[-MAX_SITUATION_CHARS:]
        i = t.find("\n")
        if 0 < i < 100:
            t = t[i + 1:]
    return t


async def _call_pro_single(
    client: genai.Client,
    situation: str,
    system_instruction: str,
    timeout_s: float = 30.0,
) -> tuple[str, str | None]:
    """Call Pro for one situation. Returns (reply, error_str|None).
    Uses streaming so we can enforce a hard timeout that kills slow /
    hung connections quickly (which are the #1 waste in bulk jobs)."""
    prompt = DISTILL_USER_PROMPT.format(situation=situation)
    config = gtypes.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.85,
        max_output_tokens=6144,  # Pro's thinking eats into this
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


async def distill(
    concurrency: int = 6,
    per_request_timeout: float = 30.0,
    shuffle_seed: int = 42,
):
    if not EXAMPLES_FILE.exists():
        print(f"[distill] ERROR: {EXAMPLES_FILE} not found.", file=sys.stderr)
        sys.exit(1)

    # Load Master Playbook — same text Pro sees in production. This is
    # critical: Pro's distilled outputs should match its production
    # behavior, which includes the playbook as system instruction.
    from wingman.training_rag import TrainingRAG
    rag = TrainingRAG()
    rag.load()
    playbook = rag.knowledge_summary or ""
    base_persona = (
        "You are Alex, a high-value dating text-game coach in the voice "
        "of Playing With Fire. Read the chat and respond with ONE short, "
        "natural, witty, specific SMS reply in Alex's voice. Output ONLY "
        "the reply text."
    )
    system_instruction = f"{base_persona}\n\n{playbook}".strip()
    print(f"[distill] System instruction: {len(system_instruction):,} chars "
          f"(persona + {len(playbook):,} chars playbook)")

    # Load + filter situations (same rules as build_finetune_dataset)
    raw = json.loads(EXAMPLES_FILE.read_text())
    entries = raw.get("examples", [])
    situations: list[dict] = []
    for e in entries:
        s = _clean_situation(e.get("situation", ""))
        if len(s) < MIN_SITUATION_CHARS:
            continue
        situations.append({
            "contact": e.get("contact", ""),
            "situation": s,
            "original_user_reply": (e.get("reply") or "").strip(),
        })
    print(f"[distill] {len(situations)} situations to label")

    # Resume support — skip situations we already got labels for
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done_keys: set[str] = set()
    if PAIRS_FILE.exists():
        with PAIRS_FILE.open() as f:
            for line in f:
                try:
                    d = json.loads(line)
                    done_keys.add(d["situation"])
                except Exception:
                    pass
        print(f"[distill] Resume: {len(done_keys)} already done, "
              f"{len(situations) - len(done_keys)} to go")
    remaining = [s for s in situations if s["situation"] not in done_keys]
    if not remaining:
        print("[distill] All situations already labeled — nothing to do.")
        return PAIRS_FILE

    # Shuffle so a single chat doesn't dominate the first 100 labels
    # (improves early-progress diversity in case the job is stopped).
    random.Random(shuffle_seed).shuffle(remaining)

    # Build one client per key so we can round-robin without hot
    # reconnects on every call.
    clients = [genai.Client(api_key=k) for k in _ALL_KEYS]
    print(f"[distill] {len(clients)} API keys, concurrency={concurrency}, "
          f"timeout={per_request_timeout}s")

    sem = asyncio.Semaphore(concurrency)
    out_lock = asyncio.Lock()
    stats = {"ok": 0, "failed": 0, "started": time.time()}

    async def worker(i: int, item: dict):
        client = clients[i % len(clients)]
        async with sem:
            # Up to 3 attempts per item — rotate key on 429 / timeout
            for attempt in range(3):
                reply, err = await _call_pro_single(
                    client, item["situation"],
                    system_instruction, per_request_timeout,
                )
                if reply and MIN_REPLY_CHARS <= len(reply) <= MAX_REPLY_CHARS:
                    async with out_lock:
                        with PAIRS_FILE.open("a", encoding="utf-8") as f:
                            f.write(json.dumps({
                                "contact": item["contact"],
                                "situation": item["situation"],
                                "pro_reply": reply,
                                "original_user_reply": item["original_user_reply"],
                            }, ensure_ascii=False) + "\n")
                        stats["ok"] += 1
                        if stats["ok"] % 25 == 0:
                            elapsed = time.time() - stats["started"]
                            rate = stats["ok"] / max(1, elapsed)
                            remaining_count = len(remaining) - stats["ok"]
                            eta = remaining_count / max(0.1, rate)
                            print(f"[distill]   {stats['ok']}/{len(remaining)} "
                                  f"({rate:.2f}/s, ETA {eta/60:.1f}min)")
                    return
                # Retry path: rotate, back off
                is_rate = "429" in (err or "") or "RESOURCE_EXHAUSTED" in (err or "")
                is_overload = "503" in (err or "") or "UNAVAILABLE" in (err or "") or "timeout" in (err or "").lower()
                if is_rate or is_overload or "timeout" in (err or "").lower():
                    # Swap to a different key on retry
                    client = clients[(i + attempt + 1) % len(clients)]
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                # Non-retryable (e.g. PROHIBITED_CONTENT) — bail immediately
                break
            stats["failed"] += 1
            print(f"[distill]   FAIL ({item['contact']}): {err}")

    tasks = [worker(i, item) for i, item in enumerate(remaining)]
    await asyncio.gather(*tasks)

    elapsed = time.time() - stats["started"]
    print()
    print("=" * 60)
    print(f"DISTILLATION COMPLETE")
    print(f"  OK:      {stats['ok']}")
    print(f"  Failed:  {stats['failed']}")
    print(f"  Elapsed: {elapsed/60:.1f} min")
    print(f"  Output:  {PAIRS_FILE}")
    print("=" * 60)
    return PAIRS_FILE


def main():
    asyncio.run(distill())


if __name__ == "__main__":
    main()
