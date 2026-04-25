"""Mine situation → reply pairs from the 121 training transcripts.

Tier-1 expansion: the user's own chats gave us 628 training examples.
The 121 PWF-style training transcripts contain HUNDREDS of additional
chat scenarios (Alex demonstrating what to reply in specific
situations). This miner uses Flash to extract every discrete
"situation + suggested reply" pair mentioned in each transcript,
giving us broader scenario coverage for the v2 fine-tune.

Output: training_dataset/mined_situations.jsonl — (contact=<transcript
name>, situation, alex_suggested_reply). Alex's suggested reply is
KEPT as a quality cross-check but NOT used as the training label.
Training labels come from re-running distill_from_pro on these
situations so the dataset label distribution stays consistent with
the existing 628 Pro-labeled pairs.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


TRANSCRIPTS_DIR = Path(__file__).parent.parent / "training"
OUT_DIR = Path(__file__).parent.parent / "training_dataset"
OUT_FILE = OUT_DIR / "mined_situations.jsonl"


# Flash is cheap + fast enough for bulk extraction. We ask it for
# structured JSON output so parsing is robust. The prompt is
# explicit: extract DISCRETE chat scenarios, not general advice.
EXTRACT_PROMPT = (
    "You are processing a dating-coach video transcript. Extract EVERY "
    "discrete chat scenario mentioned where a specific conversational "
    "exchange is shown with a recommended reply.\n\n"
    "For each scenario, output:\n"
    "  • situation: the chat messages BEFORE the recommended reply, "
    "in 'HER:' / 'ME:' format (alternating lines). Must be at least "
    "2 messages of context, maximum 12 messages. Use 'HER:' for what "
    "she sent and 'ME:' for what I sent.\n"
    "  • alex_reply: the SINGLE specific reply message Alex recommends "
    "in that scenario. Short and natural, like a real SMS. If Alex "
    "gives multiple equally-good options, pick the most characteristic "
    "one.\n"
    "  • stage: one of 'opener', 'rapport', 'banter', 'escalation', "
    "'logistics', 'revival', 'qualification'\n"
    "  • tone: one of 'playful', 'direct', 'teasing', 'sexual', "
    "'withdrawing', 'dominant', 'neutral'\n\n"
    "CRITICAL RULES:\n"
    "  • ONLY extract scenarios where BOTH the chat context AND a "
    "specific reply are shown. Skip general advice.\n"
    "  • If a transcript has no concrete chat examples, return [] — "
    "do not invent scenarios.\n"
    "  • The reply must be a MESSAGE Alex says to send, not commentary "
    "about it.\n"
    "  • Use EXACT wording when possible. Don't paraphrase replies.\n\n"
    "Return STRICT JSON only:\n"
    "{\"scenarios\": [\n"
    "  {\"situation\": \"HER: ...\\nME: ...\\nHER: ...\", "
    "\"alex_reply\": \"...\", \"stage\": \"...\", \"tone\": \"...\"}\n"
    "]}\n\n"
    "Transcript:\n{transcript}"
)


async def _mine_one(client, filename: str, content: str,
                    timeout_s: float = 60.0) -> list[dict]:
    """Extract scenarios from a single transcript."""
    from wingman.config import FLASH_MODEL
    from google.genai import types as gtypes

    if len(content.strip()) < 200:
        # Too short to have meaningful chat examples
        return []

    # Large transcripts can exceed max_output for Flash — chunk-aware
    # approach is overkill here. Cap at 60k chars (≈15k tokens in;
    # Flash handles easily) and just process.
    if len(content) > 60000:
        content = content[:60000]

    prompt = EXTRACT_PROMPT.replace("{transcript}", content)

    try:
        resp = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=FLASH_MODEL,
                contents=prompt,
                config=gtypes.GenerateContentConfig(
                    temperature=0.3,     # low for extraction
                    max_output_tokens=8192,
                ),
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        print(f"[mine]   {filename}: TIMEOUT")
        return []
    except Exception as exc:
        print(f"[mine]   {filename}: ERROR {str(exc)[:100]}")
        return []

    raw = (resp.text or "").strip()
    if not raw:
        return []

    # Strip markdown code fences if present
    import re as _re
    fence = _re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()
    m = _re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return []
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return []

    scenarios = data.get("scenarios") or []
    # Validate + filter
    good: list[dict] = []
    for s in scenarios:
        if not isinstance(s, dict):
            continue
        situation = (s.get("situation") or "").strip()
        reply = (s.get("alex_reply") or "").strip()
        if not situation or not reply:
            continue
        if len(reply) < 5 or len(reply) > 500:
            continue
        # Require BOTH speakers present in the situation
        if "HER:" not in situation or "ME:" not in situation:
            continue
        if len(situation) < 40:
            continue
        good.append({
            "contact": f"transcript:{filename}",
            "situation": situation,
            "alex_suggested_reply": reply,
            "stage": s.get("stage", ""),
            "tone": s.get("tone", ""),
        })
    return good


async def mine_all(concurrency: int = 6):
    """Walk all transcripts, extract scenarios, write to JSONL."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Resume support — skip already-processed transcripts
    done_files: set[str] = set()
    if OUT_FILE.exists():
        with OUT_FILE.open() as f:
            for line in f:
                try:
                    d = json.loads(line)
                    done_files.add(d["contact"].replace("transcript:", ""))
                except Exception:
                    pass
        print(f"[mine] Resume: {len(done_files)} transcripts already mined")

    files = sorted(TRANSCRIPTS_DIR.iterdir())
    files = [
        f for f in files
        if f.is_file() and f.suffix.lower() in (".txt", ".md", ".srt", ".vtt")
        and not f.name.startswith(".") and f.name not in done_files
    ]
    print(f"[mine] {len(files)} transcripts to process "
          f"(concurrency={concurrency})")

    if not files:
        print("[mine] Nothing to do.")
        return OUT_FILE

    from wingman.config import make_genai_client
    client = make_genai_client()

    sem = asyncio.Semaphore(concurrency)
    out_lock = asyncio.Lock()
    stats = {"ok": 0, "failed": 0, "total_pairs": 0, "started": time.time()}

    async def worker(f: Path):
        async with sem:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                stats["failed"] += 1
                return
            pairs = await _mine_one(client, f.name, content)
            if not pairs:
                async with out_lock:
                    stats["failed"] += 1
                return
            async with out_lock:
                with OUT_FILE.open("a", encoding="utf-8") as outf:
                    for p in pairs:
                        outf.write(json.dumps(p, ensure_ascii=False) + "\n")
                stats["ok"] += 1
                stats["total_pairs"] += len(pairs)
                if stats["ok"] % 10 == 0:
                    elapsed = time.time() - stats["started"]
                    rate = stats["ok"] / max(1, elapsed)
                    remaining = len(files) - stats["ok"] - stats["failed"]
                    eta = remaining / max(0.1, rate)
                    print(f"[mine] {stats['ok']}/{len(files)} "
                          f"(pairs={stats['total_pairs']}, "
                          f"rate={rate:.2f}/s, ETA {eta/60:.1f}min)")

    await asyncio.gather(*(worker(f) for f in files))

    elapsed = time.time() - stats["started"]
    print()
    print("=" * 60)
    print(f"TRANSCRIPT MINING COMPLETE")
    print(f"  OK transcripts:   {stats['ok']}")
    print(f"  Failed / empty:   {stats['failed']}")
    print(f"  Total new pairs:  {stats['total_pairs']}")
    print(f"  Elapsed:          {elapsed/60:.1f} min")
    print(f"  Output file:      {OUT_FILE}")
    print("=" * 60)
    return OUT_FILE


def main():
    asyncio.run(mine_all())


if __name__ == "__main__":
    main()
