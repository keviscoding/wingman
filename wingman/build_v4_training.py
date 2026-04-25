"""Build the v4 training JSONL from Pro-distilled pairs.

KEY DIFFERENCE from v3: the Master Playbook is INCLUDED in every
training row's system instruction, not just at inference. This teaches
the model to ACT on the playbook rules during training, so at
inference the playbook's strategic guidance is something the model
knows how to apply — not something it's reading for the first time.

This is the single biggest architectural lift for v4. It roughly
quadruples per-row token count (and therefore training cost), but
it's the technique that makes the gap between fine-tune-voice and
Pro-strategy close.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "training_dataset"
PAIRS_FILE = DATA_DIR / "v4_pro_pairs.jsonl"
OUT_TRAIN = DATA_DIR / "v4_train.jsonl"
OUT_VAL = DATA_DIR / "v4_val.jsonl"
OUT_STATS = DATA_DIR / "v4_training_stats.json"

PLAYBOOK_PATH = Path(__file__).parent.parent / "training" / ".master_playbook.json"

PERSONA_PREFIX = (
    "You are Alex, a high-value dating text-game coach in the voice of "
    "Playing With Fire. Read the conversation and respond with ONE short "
    "natural SMS reply — witty, specific, punchy, emotionally aware, "
    "never generic. Output ONLY the reply text."
)


def _load_playbook() -> str:
    if not PLAYBOOK_PATH.exists():
        return ""
    try:
        d = json.loads(PLAYBOOK_PATH.read_text())
        return d.get("playbook") or ""
    except Exception:
        return ""


def _format_context(ctx_messages):
    lines = []
    for m in ctx_messages:
        tag = "ME" if m.get("speaker") == "me" else "HER"
        text = (m.get("text") or "").strip()
        if text:
            lines.append(f"{tag}: {text}")
    return "\n".join(lines)


def _build_row(system_instruction: str, ctx_messages, reply: str) -> dict:
    user_text = (
        "Conversation so far:\n"
        f"{_format_context(ctx_messages)}\n\n"
        "Write the next reply I should send."
    )
    return {
        "systemInstruction": {
            "role": "system",
            "parts": [{"text": system_instruction}],
        },
        "contents": [
            {"role": "user",  "parts": [{"text": user_text}]},
            {"role": "model", "parts": [{"text": reply}]},
        ],
    }


def build(split: float = 0.03, seed: int = 42, verbose: bool = True) -> dict:
    if not PAIRS_FILE.exists():
        raise FileNotFoundError(
            f"{PAIRS_FILE} not found — run distill_v4_from_pro first"
        )

    playbook = _load_playbook()
    system_instruction = PERSONA_PREFIX + "\n\n" + playbook if playbook else PERSONA_PREFIX
    if verbose:
        print(f"[v4-train] System instruction: {len(system_instruction):,} chars "
              f"(persona + playbook={len(playbook):,} chars)")

    rows: list[dict] = []
    with PAIRS_FILE.open() as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            reply = (d.get("pro_reply") or "").strip()
            ctx = d.get("context_messages") or []
            if not reply or len(reply) < 5 or len(reply) > 500:
                continue
            if not ctx:
                continue
            rows.append(_build_row(system_instruction, ctx, reply))

    if verbose:
        print(f"[v4-train] Built {len(rows)} training rows")

    rng = random.Random(seed)
    rng.shuffle(rows)
    n_val = max(30, int(len(rows) * split))
    val_rows = rows[:n_val]
    train_rows = rows[n_val:]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_TRAIN.open("w", encoding="utf-8") as f:
        for r in train_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with OUT_VAL.open("w", encoding="utf-8") as f:
        for r in val_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def _tok(s): return max(1, len(s) // 4)
    train_tokens = 0
    for r in train_rows:
        train_tokens += _tok(r["systemInstruction"]["parts"][0]["text"])
        for c in r["contents"]:
            train_tokens += _tok(c["parts"][0]["text"])
    epochs = 3
    billed = train_tokens * epochs
    cost = billed / 1_000_000 * 5.0

    stats = {
        "train_count": len(train_rows),
        "val_count": len(val_rows),
        "tokens_train": train_tokens,
        "epochs": epochs,
        "billed_training_tokens": billed,
        "estimated_cost_usd": round(cost, 2),
        "playbook_chars_per_row": len(playbook),
    }
    OUT_STATS.write_text(json.dumps(stats, indent=2))

    if verbose:
        print()
        print("=" * 60)
        print("V4 TRAINING DATASET BUILT")
        print(f"  Train:               {stats['train_count']}")
        print(f"  Validation:          {stats['val_count']}")
        print(f"  Train tokens:        {stats['tokens_train']:,}")
        print(f"  Billed (3 epochs):   {stats['billed_training_tokens']:,}")
        print(f"  Est. training cost:  ${stats['estimated_cost_usd']}")
        print(f"  Train JSONL:         {OUT_TRAIN} ({OUT_TRAIN.stat().st_size//1024} KB)")
        print(f"  Val JSONL:           {OUT_VAL} ({OUT_VAL.stat().st_size//1024} KB)")
        print("=" * 60)
    return stats


if __name__ == "__main__":
    build()
