"""Extract CLEANED situations for Pro distillation (v4 pipeline).

Takes the same source data v3 used (mined Alex transcript arcs +
user's chat arcs) but applies aggressive hygiene BEFORE we pay for
Pro distillation:

  • Dedupe identical replies (cap N per unique reply)
  • Drop replies under 10 chars (generic acks like "yes", "mmm")
  • Drop pure acknowledgment patterns
  • Drop situations where the reply is a literal copy-paste from the
    chat history (the "fake callback" bug v3 was learning)
  • Skip examples from chats flagged as bad outcomes
  • Subsample within each arc (MAX_EXAMPLES_PER_ARC tighter)

The output ``v4_situations.jsonl`` is what gets fed to Pro for
re-labeling. Every row is:

  {
    "source": "transcript" | "user_chat",
    "context_messages": [{"speaker": "them", "text": "..."}, ...],
    "original_reply": "<the reply from source, for reference only>"
  }

The Pro-distiller reads context_messages, ignores original_reply, and
produces a fresh strategically-correct Alex-voice label.
"""

from __future__ import annotations

import json
import re
import random
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "training_dataset"
ARCS_FILE = DATA_DIR / "mined_arcs.jsonl"
CHATS_DIR = Path(__file__).parent.parent / "chats"
OUT_FILE = DATA_DIR / "v4_situations.jsonl"
STATS_FILE = DATA_DIR / "v4_hygiene_stats.json"


# Tuning knobs — tighter than v3 on purpose
MIN_CONTEXT_MSGS = 2
MAX_CONTEXT_MSGS = 40         # was 60 in v3 — shorter is more in-distribution
MIN_REPLY_CHARS = 10           # was 3 in v3 — kills "yes/mmm/perfect"
MAX_REPLY_CHARS = 400          # was 500 in v3 — kills paragraph explanations
MAX_EXAMPLES_PER_ARC = 20      # was 30 — less oversampling of long arcs
MAX_DUP_REPLIES = 3            # cap instances of identical reply across dataset


# Generic acknowledgments that add no training signal. We drop them
# even if > 10 chars when they fully match these patterns.
_ACK_PATTERNS = [
    r"^ok(ay)?!?$",
    r"^(yes|no|sure|cool|nice|perfect)\.?!?$",
    r"^(lol|lmao|haha|xd)\.?!?$",
    r"^(mhm+|mm+|hmm+)$",
    r"^sounds (good|great|fun)\.?!?$",
    r"^(true|exactly|agreed)\.?!?$",
    r"^(right|really)\??!?$",
    r"^(same|def(initely)?)\.?!?$",
]
_ACK_RE = re.compile("|".join(_ACK_PATTERNS), re.IGNORECASE)


def _is_generic_ack(text: str) -> bool:
    return bool(_ACK_RE.match(text.strip()))


def _is_copy_paste_callback(reply: str, context_msgs: list[dict]) -> bool:
    """Detects the 'fake callback' pattern where the reply is literally
    a substring copy of earlier chat content. Real callbacks transform
    the prior line — this flag catches lazy echoes."""
    r = reply.strip().lower()
    if len(r) < 12:
        return False
    # Exact match or near-exact substring match against prior messages
    for m in context_msgs:
        t = (m.get("text") or "").strip().lower()
        if not t:
            continue
        # Large overlap is a red flag
        if r == t:
            return True
        if len(r) >= 15 and r in t:
            return True
        if len(t) >= 15 and t in r:
            return True
    return False


def _format_messages(messages):
    """Normalize message list to [{speaker, text}] records."""
    out = []
    for m in messages:
        speaker = m.get("speaker", "")
        text = (m.get("text") or "").strip()
        if speaker not in ("me", "them") or not text:
            continue
        out.append({"speaker": speaker, "text": text})
    return out


def _extract_rows_from_arc(source: str, messages: list[dict]) -> list[dict]:
    """For an arc, produce candidate (context, reply) rows obeying
    hygiene rules. Subsamples to MAX_EXAMPLES_PER_ARC if needed."""
    msgs = _format_messages(messages)
    candidates: list[tuple[int, dict]] = []
    for i, m in enumerate(msgs):
        if m["speaker"] != "me":
            continue
        if i < MIN_CONTEXT_MSGS:
            continue
        reply = m["text"]
        if len(reply) < MIN_REPLY_CHARS or len(reply) > MAX_REPLY_CHARS:
            continue
        if _is_generic_ack(reply):
            continue
        # Skip bracketed media placeholders
        if reply.startswith("[") and reply.endswith("]") and len(reply) < 30:
            continue
        start = max(0, i - MAX_CONTEXT_MSGS)
        ctx = msgs[start:i]
        if not any(p["speaker"] == "them" for p in ctx):
            continue
        if _is_copy_paste_callback(reply, ctx):
            continue
        candidates.append((i, {
            "source": source,
            "context_messages": ctx,
            "original_reply": reply,
        }))

    if len(candidates) > MAX_EXAMPLES_PER_ARC:
        # Even sampling across the arc to preserve stage diversity
        step = len(candidates) / MAX_EXAMPLES_PER_ARC
        sampled = [candidates[int(k * step)] for k in range(MAX_EXAMPLES_PER_ARC)]
        candidates = sampled

    return [row for (_, row) in candidates]


def _load_transcript_arcs() -> list[list[dict]]:
    if not ARCS_FILE.exists():
        return []
    arcs = []
    with ARCS_FILE.open() as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            msgs = d.get("messages") or []
            if len(msgs) >= 6:
                arcs.append(msgs)
    return arcs


def _load_user_chat_arcs() -> list[list[dict]]:
    """Load each user chat as an arc, skipping bad-outcome flagged ones."""
    arcs = []
    if not CHATS_DIR.exists():
        return arcs
    for f in sorted(CHATS_DIR.glob("*.json")):
        if f.name.startswith("."):
            continue
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        meta = data.get("meta") or {}
        if meta.get("bad_outcome"):
            continue
        msgs = data.get("messages") or []
        if len(msgs) >= 6:
            arcs.append(msgs)
    return arcs


def build(seed: int = 42, verbose: bool = True) -> dict:
    transcript_arcs = _load_transcript_arcs()
    user_arcs = _load_user_chat_arcs()
    if verbose:
        print(f"[v4-situ] Loaded {len(transcript_arcs)} transcript arcs, "
              f"{len(user_arcs)} user-chat arcs")

    raw_rows: list[dict] = []
    for arc in transcript_arcs:
        raw_rows.extend(_extract_rows_from_arc("transcript", arc))
    for arc in user_arcs:
        raw_rows.extend(_extract_rows_from_arc("user_chat", arc))

    if verbose:
        print(f"[v4-situ] Rows after per-arc filtering: {len(raw_rows)}")

    # Cross-dataset dedup — cap the number of times any single "reply
    # text" can appear. Prevents "Don't be shy" from contributing 14x.
    rng = random.Random(seed)
    rng.shuffle(raw_rows)
    reply_counts: Counter = Counter()
    kept: list[dict] = []
    for row in raw_rows:
        reply_key = row["original_reply"].strip().lower()
        if reply_counts[reply_key] >= MAX_DUP_REPLIES:
            continue
        reply_counts[reply_key] += 1
        kept.append(row)

    if verbose:
        print(f"[v4-situ] Rows after cross-arc dedup "
              f"(max {MAX_DUP_REPLIES} per unique reply): {len(kept)}")

    # Write
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_FILE.open("w", encoding="utf-8") as f:
        for row in kept:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Stats
    source_counts = Counter(r["source"] for r in kept)
    reply_length_stats = [len(r["original_reply"]) for r in kept]
    context_length_stats = [
        sum(len(m["text"]) for m in r["context_messages"])
        for r in kept
    ]
    stats = {
        "input_arcs_transcripts": len(transcript_arcs),
        "input_arcs_user_chats": len(user_arcs),
        "rows_after_arc_filter": len(raw_rows),
        "rows_after_dedup": len(kept),
        "by_source": dict(source_counts),
        "reply_length": {
            "min": min(reply_length_stats, default=0),
            "max": max(reply_length_stats, default=0),
            "median": sorted(reply_length_stats)[len(reply_length_stats)//2] if reply_length_stats else 0,
        },
        "context_length_chars": {
            "min": min(context_length_stats, default=0),
            "max": max(context_length_stats, default=0),
            "median": sorted(context_length_stats)[len(context_length_stats)//2] if context_length_stats else 0,
        },
        "unique_replies": len(reply_counts),
    }
    STATS_FILE.write_text(json.dumps(stats, indent=2))

    if verbose:
        print()
        print("=" * 60)
        print("V4 SITUATION EXTRACTION COMPLETE")
        print(f"  Situations ready for Pro: {stats['rows_after_dedup']}")
        print(f"  By source:                {stats['by_source']}")
        print(f"  Unique replies seen:      {stats['unique_replies']}")
        print(f"  Reply length (median):    {stats['reply_length']['median']} chars")
        print(f"  Output:                   {OUT_FILE}")
        print("=" * 60)
    return stats


if __name__ == "__main__":
    build()
