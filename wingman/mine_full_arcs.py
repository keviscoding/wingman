"""Mine FULL chat arcs from the 121 PWF transcripts for v3 training.

v2 miner pulled short (2-12 message) fragments and threw away the
beautiful full arcs at the bottom of each transcript. This miner fixes
that. For every transcript file:

  1. Flash reads the file
  2. Flash identifies the distinct chat arcs (a single transcript can
     contain multiple women — we MUST separate them so we don't train
     on cross-chat context bleeding)
  3. For each arc, Flash emits the ordered message list (speaker +
     text) from first message to the natural end
  4. We save each arc as an independent record

The output (``training_dataset/mined_arcs.jsonl``) is then fed into the
progressive training-example builder which, for each arc, generates N
training rows (one per Alex message at progressively larger context).

This gives v3 the arc-awareness v2 lacked: the model learns not just
"given these 10 messages, reply X" but "given THIS specific 50-message
arc with THIS personality type and THIS level of built-up investment,
reply X."
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
OUT_FILE = OUT_DIR / "mined_arcs.jsonl"

# We send the full transcript to Flash. 131k tokens in — no chunking
# needed.  Flash 3 handles this easily and is still fast + cheap.
MAX_TRANSCRIPT_CHARS = 120_000

ARC_EXTRACT_PROMPT = """You are parsing a dating-coach video transcript from the "Playing With Fire" channel. Each file has two parts:

  A) The video's spoken transcript (Alex narrating what he did), sometimes across MULTIPLE chats with different women
  B) The RAW text conversation transcripts at the bottom (labeled "Conversation 1", "Conversation 2", etc.)

Your job: extract every DISTINCT CHAT ARC as a complete, ordered sequence of messages.

CRITICAL RULES — READ CAREFULLY:

  1. A single transcript can contain MULTIPLE chat arcs with DIFFERENT women. You MUST separate them. Never mix messages from different women into the same arc.

  2. A single chat arc can span multiple "Conversation N" blocks in the raw section — these are usually platform hops with the SAME woman (e.g. Hinge → iMessage → new iMessage). Look for signals like:
       • Both reference the same context / inside jokes
       • The video commentary says "now on iMessage" or similar
       • Conversation content flows naturally from the previous block
     If the flow is continuous, concatenate the blocks into ONE arc.

  3. If the transcript only has ONE woman, emit a single arc containing all her messages from start to finish.

  4. If the transcript contains short example snippets (no full arc) and then a separate "main" full arc, emit ONLY the main full arc. Do NOT emit tiny fragment-only arcs as standalone arcs — those were already covered by a previous miner.

  5. Messages must be ORDERED chronologically as they appear in the transcript. Speaker field is exactly "me" (for Alex) or "them" (for the woman).

  6. CLEAN the messages: keep exact wording but strip timestamps, redacted building names [redacted], emoji descriptions in brackets, and image-description blocks like "[Image of a baby...]". Keep short bracketed placeholders like [GIF] or [photo] if they carry meaning; drop them if they don't.

  7. Skip arcs with fewer than 6 messages total — too thin for arc training.

Return STRICT JSON only:

{
  "arcs": [
    {
      "woman_label": "short identifier e.g. 'girl1' or 'insomniac' or 'cuban girl'",
      "platform_path": "e.g. 'hinge→imessage' or 'tinder'",
      "outcome_hint": "close / meet-up / ghosting / unclear",
      "messages": [
        {"speaker": "me", "text": "..."},
        {"speaker": "them", "text": "..."}
      ]
    }
  ]
}

If no complete arcs exist, return {"arcs": []}.

Transcript:
"""


async def _extract_arcs(client, filename: str, content: str,
                         timeout_s: float = 240.0) -> list[dict]:
    """Flash parses one transcript, returns list of arc records."""
    from wingman.config import FLASH_MODEL
    from google.genai import types as gtypes

    if len(content) > MAX_TRANSCRIPT_CHARS:
        content = content[:MAX_TRANSCRIPT_CHARS]

    prompt = ARC_EXTRACT_PROMPT + content

    try:
        resp = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=FLASH_MODEL,
                contents=prompt,
                config=gtypes.GenerateContentConfig(
                    temperature=0.15,  # deterministic extraction
                    max_output_tokens=32768,
                ),
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        print(f"[arcs]   {filename}: TIMEOUT")
        return []
    except Exception as exc:
        print(f"[arcs]   {filename}: ERROR {str(exc)[:120]}")
        return []

    raw = (resp.text or "").strip()
    if not raw:
        return []

    # Strip markdown fences
    import re
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return []
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        print(f"[arcs]   {filename}: bad JSON")
        return []

    arcs = data.get("arcs") or []
    validated: list[dict] = []
    for i, arc in enumerate(arcs):
        if not isinstance(arc, dict):
            continue
        msgs = arc.get("messages") or []
        if not isinstance(msgs, list) or len(msgs) < 6:
            continue
        # Sanity-check each message
        clean_msgs = []
        for m_ in msgs:
            if not isinstance(m_, dict):
                continue
            speaker = m_.get("speaker", "")
            text = (m_.get("text") or "").strip()
            if speaker not in ("me", "them") or not text:
                continue
            if len(text) > 1000:
                text = text[:1000]
            clean_msgs.append({"speaker": speaker, "text": text})
        if len(clean_msgs) < 6:
            continue
        # Arcs must have BOTH speakers represented
        if not any(m_["speaker"] == "me" for m_ in clean_msgs):
            continue
        if not any(m_["speaker"] == "them" for m_ in clean_msgs):
            continue
        validated.append({
            "transcript": filename,
            "arc_index": i,
            "woman_label": arc.get("woman_label", f"{filename}#arc{i}"),
            "platform_path": arc.get("platform_path", ""),
            "outcome_hint": arc.get("outcome_hint", ""),
            "messages": clean_msgs,
        })
    return validated


async def mine_all_arcs(concurrency: int = 5):
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Resume support
    done_files: set[str] = set()
    if OUT_FILE.exists():
        with OUT_FILE.open() as f:
            for line in f:
                try:
                    d = json.loads(line)
                    done_files.add(d["transcript"])
                except Exception:
                    pass
        print(f"[arcs] Resume: {len(done_files)} transcripts already processed")

    files = sorted(TRANSCRIPTS_DIR.iterdir())
    files = [
        f for f in files
        if f.is_file() and f.suffix.lower() in (".txt", ".md")
        and not f.name.startswith(".") and f.name not in done_files
    ]
    print(f"[arcs] {len(files)} transcripts to process (concurrency={concurrency})")

    if not files:
        print("[arcs] Nothing to do.")
        return OUT_FILE

    from wingman.config import make_genai_client
    client = make_genai_client()

    sem = asyncio.Semaphore(concurrency)
    out_lock = asyncio.Lock()
    stats = {"ok": 0, "failed": 0, "total_arcs": 0, "total_msgs": 0,
             "started": time.time()}

    async def worker(f: Path):
        async with sem:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                stats["failed"] += 1
                return
            arcs = await _extract_arcs(client, f.name, content)
            if not arcs:
                async with out_lock:
                    stats["failed"] += 1
                return
            async with out_lock:
                with OUT_FILE.open("a", encoding="utf-8") as outf:
                    for arc in arcs:
                        outf.write(json.dumps(arc, ensure_ascii=False) + "\n")
                stats["ok"] += 1
                stats["total_arcs"] += len(arcs)
                stats["total_msgs"] += sum(len(a["messages"]) for a in arcs)
                if stats["ok"] % 10 == 0:
                    elapsed = time.time() - stats["started"]
                    rate = stats["ok"] / max(1, elapsed)
                    remaining = len(files) - stats["ok"] - stats["failed"]
                    eta = remaining / max(0.1, rate)
                    print(f"[arcs] {stats['ok']}/{len(files)} "
                          f"(arcs={stats['total_arcs']}, "
                          f"msgs={stats['total_msgs']}, "
                          f"rate={rate:.2f}/s, ETA {eta/60:.1f}min)")

    await asyncio.gather(*(worker(f) for f in files))

    elapsed = time.time() - stats["started"]
    print()
    print("=" * 60)
    print("FULL-ARC MINING COMPLETE")
    print(f"  OK transcripts:   {stats['ok']}")
    print(f"  Failed / empty:   {stats['failed']}")
    print(f"  Total arcs:       {stats['total_arcs']}")
    print(f"  Total messages:   {stats['total_msgs']}")
    print(f"  Avg msgs/arc:     {stats['total_msgs']/max(1,stats['total_arcs']):.1f}")
    print(f"  Elapsed:          {elapsed/60:.1f} min")
    print(f"  Output:           {OUT_FILE}")
    print("=" * 60)
    return OUT_FILE


def main():
    asyncio.run(mine_all_arcs())


if __name__ == "__main__":
    main()
