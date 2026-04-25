"""Build the v3 fine-tune dataset from FULL chat arcs with progressive
context.

For every arc (either mined from a PWF transcript or loaded from the
user's own chats), we walk through and create ONE training example for
every Alex message. Each example shows the model everything that came
BEFORE that message as context, and teaches it to produce that exact
reply.

Result: a single 50-message arc contributes ~25 training examples, one
for each decision point Alex actually made. The model learns:
  • What openers look like (short context)
  • What mid-arc recovery moves look like (medium context)
  • What close-phase decisions look like (long context)

Plus the model implicitly learns the personality/arc awareness we've
been missing — because every example DOES include all prior messages
of that specific arc.

Multi-arc awareness: the miner already separated transcripts containing
multiple women into distinct arcs, so we never train the model on
context that bleeds across women. Each arc is an island.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "training_dataset"
ARCS_FILE = DATA_DIR / "mined_arcs.jsonl"
OUT_TRAIN = DATA_DIR / "v3_train.jsonl"
OUT_VAL = DATA_DIR / "v3_val.jsonl"
OUT_STATS = DATA_DIR / "v3_stats.json"

CHATS_DIR = Path(__file__).parent.parent / "chats"

# Matches v2's system instruction so the tuned model stays in the same
# persona family. Don't change unless we re-think the pipeline end-to-end.
SYSTEM_INSTRUCTION = (
    "You are Alex, a high-value dating text-game coach in the voice of "
    "Playing With Fire. Read the conversation and respond with ONE short "
    "natural SMS reply — witty, specific, punchy, emotionally aware, "
    "never generic. Output ONLY the reply text."
)

# Tuning knobs
MIN_CONTEXT_MSGS = 2       # need at least some context before predicting
MAX_CONTEXT_MSGS = 60      # cap extremely long arcs (>60 msgs of history)
MIN_REPLY_CHARS = 3
MAX_REPLY_CHARS = 500
MAX_EXAMPLES_PER_ARC = 30  # subsample if one arc would produce too many


def _format_context(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        speaker = m.get("speaker", "")
        text = (m.get("text") or "").strip()
        if not text:
            continue
        tag = "ME" if speaker == "me" else "HER"
        lines.append(f"{tag}: {text}")
    return "\n".join(lines)


def _build_row(context_msgs: list[dict], target_reply: str) -> dict:
    """Vertex supervised-tuning JSONL row."""
    transcript_text = _format_context(context_msgs)
    user_text = (
        "Conversation so far:\n"
        f"{transcript_text}\n\n"
        "Write the next reply I should send."
    )
    return {
        "systemInstruction": {
            "role": "system",
            "parts": [{"text": SYSTEM_INSTRUCTION}],
        },
        "contents": [
            {"role": "user",  "parts": [{"text": user_text}]},
            {"role": "model", "parts": [{"text": target_reply}]},
        ],
    }


def _rows_from_arc(messages: list[dict]) -> list[dict]:
    """For an arc of N messages, generate one training row per 'me'
    message with the preceding context as the prompt. Caps at
    MAX_EXAMPLES_PER_ARC by sampling evenly across the arc so we cover
    early/mid/late moves."""
    candidates: list[tuple[int, dict]] = []
    for i, m in enumerate(messages):
        if m.get("speaker") != "me":
            continue
        if i < MIN_CONTEXT_MSGS:
            continue
        reply = (m.get("text") or "").strip()
        if not reply or len(reply) < MIN_REPLY_CHARS or len(reply) > MAX_REPLY_CHARS:
            continue
        # Drop bare media placeholders as the training target
        if reply.startswith("[") and reply.endswith("]") and len(reply) < 30:
            continue
        # Context window: all preceding messages, capped
        start = max(0, i - MAX_CONTEXT_MSGS)
        ctx = messages[start:i]
        if not any(p.get("speaker") == "them" for p in ctx):
            continue
        candidates.append((i, _build_row(ctx, reply)))

    if len(candidates) > MAX_EXAMPLES_PER_ARC:
        # Evenly spaced sample so we keep early / mid / late context examples
        step = len(candidates) / MAX_EXAMPLES_PER_ARC
        sampled = [candidates[int(k * step)] for k in range(MAX_EXAMPLES_PER_ARC)]
        candidates = sampled

    return [r for (_, r) in candidates]


def _load_mined_arcs() -> list[list[dict]]:
    """Load arcs from the PWF transcript miner."""
    arcs: list[list[dict]] = []
    if not ARCS_FILE.exists():
        print(f"[build] NOTE: {ARCS_FILE} not found — run mine_full_arcs first")
        return arcs
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
    """Load each of the user's chats as one arc. Skips chats flagged as
    bad outcomes (we don't want to train on our failures as if they
    were correct). Requires at least 6 total messages."""
    arcs: list[list[dict]] = []
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
            continue  # skip flagged-bad chats
        msgs_raw = data.get("messages") or []
        # Normalize to the same {speaker, text} shape as mined arcs
        msgs: list[dict] = []
        for m in msgs_raw:
            speaker = m.get("speaker", "")
            text = (m.get("text") or "").strip()
            if speaker not in ("me", "them") or not text:
                continue
            msgs.append({"speaker": speaker, "text": text})
        if len(msgs) >= 6:
            arcs.append(msgs)
    return arcs


def build(split: float = 0.03, seed: int = 42, verbose: bool = True) -> dict:
    transcript_arcs = _load_mined_arcs()
    user_arcs = _load_user_chat_arcs()

    if verbose:
        print(f"[build] Loaded {len(transcript_arcs)} transcript arcs, "
              f"{len(user_arcs)} user-chat arcs")

    all_rows: list[dict] = []
    stats = {"from_transcripts": 0, "from_user_chats": 0}

    for arc in transcript_arcs:
        rows = _rows_from_arc(arc)
        all_rows.extend(rows)
        stats["from_transcripts"] += len(rows)

    for arc in user_arcs:
        rows = _rows_from_arc(arc)
        all_rows.extend(rows)
        stats["from_user_chats"] += len(rows)

    if verbose:
        print(f"[build] Generated training rows: "
              f"{stats['from_transcripts']} from transcripts + "
              f"{stats['from_user_chats']} from user chats = "
              f"{len(all_rows)} total")

    # Shuffle + split
    rng = random.Random(seed)
    rng.shuffle(all_rows)
    n_val = max(30, int(len(all_rows) * split))
    val = all_rows[:n_val]
    train = all_rows[n_val:]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_TRAIN.open("w", encoding="utf-8") as f:
        for r in train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with OUT_VAL.open("w", encoding="utf-8") as f:
        for r in val:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Token estimate
    def _tok(s):
        return max(1, len(s) // 4)
    train_tokens = 0
    for r in train:
        train_tokens += _tok(r["systemInstruction"]["parts"][0]["text"])
        for c in r["contents"]:
            train_tokens += _tok(c["parts"][0]["text"])
    epochs = 3
    billed = train_tokens * epochs
    cost = billed / 1_000_000 * 5.0

    stats.update({
        "train_count": len(train),
        "val_count": len(val),
        "tokens_train": train_tokens,
        "epochs": epochs,
        "billed_training_tokens": billed,
        "estimated_cost_usd": round(cost, 2),
    })
    OUT_STATS.write_text(json.dumps(stats, indent=2))

    if verbose:
        print()
        print("=" * 60)
        print("V3 DATASET BUILD COMPLETE")
        print(f"  Train:             {stats['train_count']}")
        print(f"  Validation:        {stats['val_count']}")
        print(f"  Train tokens:      {stats['tokens_train']:,}")
        print(f"  Billed (3 epochs): {stats['billed_training_tokens']:,}")
        print(f"  Estimated cost:    ${stats['estimated_cost_usd']}")
        print(f"  Train JSONL:       {OUT_TRAIN} ({OUT_TRAIN.stat().st_size//1024} KB)")
        print(f"  Val JSONL:         {OUT_VAL} ({OUT_VAL.stat().st_size//1024} KB)")
        print("=" * 60)
    return stats


if __name__ == "__main__":
    build()
