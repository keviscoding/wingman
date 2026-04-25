"""Build a Vertex-AI-formatted JSONL training dataset from Wingman's
Examples Library.

Path 1 design
-------------
We fine-tune on (situation -> single-reply) pairs. Training the model
to produce ONE Alex-voiced reply is cleaner than training it on the
5-option JSON format because:
  • Our ground-truth data (your actual sent messages) is single-reply.
  • Each example is a real signal, not a synthesized variant.
  • Style learned here carries over when the model is prompted for
    multi-reply JSON output at inference time (base instruction-following
    stays intact after supervised fine-tuning).

The format matches Google's supervised-tuning schema:
  {"systemInstruction": {"role": "system", "parts": [{"text": "..."}]},
   "contents": [
     {"role": "user",  "parts": [{"text": "Conversation:\n..."}]},
     {"role": "model", "parts": [{"text": "<my chosen reply>"}]}
   ]}

Output: ``training_dataset/wingman_finetune.jsonl`` (+ a preview sample
for human inspection before anything is uploaded).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

try:
    # Optional — nicer tokenization than len()//4 if installed
    import tiktoken  # type: ignore
    _enc = tiktoken.get_encoding("cl100k_base")
    def _count_tokens(s: str) -> int:
        return len(_enc.encode(s))
except Exception:
    def _count_tokens(s: str) -> int:
        # Rough approximation: 4 chars ≈ 1 token. Close enough for
        # budgeting fine-tuning cost within ±15%.
        return max(1, len(s) // 4)


EXAMPLES_FILE = Path(__file__).parent.parent / "examples_library" / ".examples.json"
OUT_DIR = Path(__file__).parent.parent / "training_dataset"
OUT_JSONL = OUT_DIR / "wingman_finetune.jsonl"
OUT_PREVIEW = OUT_DIR / "wingman_finetune_preview.json"
OUT_SUMMARY = OUT_DIR / "wingman_finetune_summary.json"


# Minimal system instruction. We WANT this short — the whole point of
# fine-tuning is to bake the Alex persona + style into weights so the
# model doesn't need 10k chars of playbook at inference time. Keep it
# focused on the task shape + persona pointer.
SYSTEM_INSTRUCTION = (
    "You are Alex, a high-value dating text-game coach in the voice of "
    "Playing With Fire. Read the conversation and reply with ONE short, "
    "natural SMS-style message that matches the user's personal style: "
    "witty, specific, punchy, emotionally aware, never generic. No "
    "preambles. No hashtags. Just the reply text."
)


# ---------------------------------------------------------------------------
# Filters / guards
# ---------------------------------------------------------------------------

MIN_SITUATION_CHARS = 40      # at least 2 real messages of context
MIN_REPLY_CHARS = 5
MAX_REPLY_CHARS = 500
MAX_SITUATION_CHARS = 3000    # cap runaway contexts (~750 tokens)


def _clean_reply(text: str) -> str:
    """Trim whitespace, drop suspiciously bracketed media placeholders
    that slipped past the library extractor."""
    t = (text or "").strip()
    # Drop examples that are pure placeholders
    if t.startswith("[") and t.endswith("]") and len(t) < 30:
        return ""
    return t


def _clean_situation(text: str) -> str:
    t = (text or "").strip()
    if len(t) > MAX_SITUATION_CHARS:
        # Keep the tail — the part of the chat closest to the reply
        # carries the most relevant signal.
        t = t[-MAX_SITUATION_CHARS:]
        # Trim to a line boundary so we don't start mid-sentence
        i = t.find("\n")
        if 0 < i < 100:
            t = t[i + 1:]
    return t


def _build_example(situation: str, reply: str) -> dict:
    """Vertex supervised-tuning JSONL row."""
    # Wrap the situation in a minimal user instruction so the model knows
    # what to do. Keep it identical across every row — stable pattern
    # makes fine-tuning converge faster.
    user_text = (
        "Conversation so far:\n"
        f"{situation}\n\n"
        "Write the next reply I should send."
    )
    return {
        "systemInstruction": {
            "role": "system",
            "parts": [{"text": SYSTEM_INSTRUCTION}],
        },
        "contents": [
            {"role": "user",  "parts": [{"text": user_text}]},
            {"role": "model", "parts": [{"text": reply}]},
        ],
    }


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------


def build(
    split: float = 0.05,
    shuffle_seed: int = 42,
    dry_run: bool = False,
    verbose: bool = True,
):
    if not EXAMPLES_FILE.exists():
        print(f"[build] ERROR: {EXAMPLES_FILE} not found. "
              f"Run the server once so the Examples Library bootstraps.",
              file=sys.stderr)
        sys.exit(1)

    raw = json.loads(EXAMPLES_FILE.read_text())
    entries = raw.get("examples", [])
    print(f"[build] Loaded {len(entries)} examples from library")

    # Filter + format
    rows: list[dict] = []
    skipped = {"short_situation": 0, "short_reply": 0, "long_reply": 0,
               "empty_after_clean": 0}
    per_contact: dict[str, int] = {}

    for e in entries:
        contact = e.get("contact", "")
        situation = _clean_situation(e.get("situation", ""))
        reply = _clean_reply(e.get("reply", ""))

        if not reply:
            skipped["empty_after_clean"] += 1
            continue
        if len(reply) < MIN_REPLY_CHARS:
            skipped["short_reply"] += 1
            continue
        if len(reply) > MAX_REPLY_CHARS:
            skipped["long_reply"] += 1
            continue
        if len(situation) < MIN_SITUATION_CHARS:
            skipped["short_situation"] += 1
            continue

        rows.append(_build_example(situation, reply))
        per_contact[contact] = per_contact.get(contact, 0) + 1

    print(f"[build] Kept {len(rows)} / {len(entries)} examples "
          f"(skipped: {skipped})")
    print(f"[build] Represented chats: {len(per_contact)}")
    top_contacts = sorted(per_contact.items(), key=lambda kv: -kv[1])[:5]
    print("[build] Top contributing chats:")
    for c, n in top_contacts:
        print(f"         {c}: {n} examples")

    # Shuffle for fairness across epochs (a single chat's examples shouldn't
    # dominate any training batch)
    rng = random.Random(shuffle_seed)
    rng.shuffle(rows)

    # Train / validation split
    n_val = max(10, int(len(rows) * split))
    validation = rows[:n_val]
    training = rows[n_val:]
    print(f"[build] Train / validation split: {len(training)} / {len(validation)}")

    # Token + cost math
    tok_total = 0
    for r in rows:
        tok_total += _count_tokens(r["systemInstruction"]["parts"][0]["text"])
        for c in r["contents"]:
            tok_total += _count_tokens(c["parts"][0]["text"])
    training_tokens_per_epoch = sum(
        _count_tokens(r["systemInstruction"]["parts"][0]["text"])
        + sum(_count_tokens(c["parts"][0]["text"]) for c in r["contents"])
        for r in training
    )
    epochs = 3
    billed_tokens = training_tokens_per_epoch * epochs
    price_per_m_2_5_flash = 5.0
    estimated_cost = billed_tokens / 1_000_000 * price_per_m_2_5_flash

    summary = {
        "total_input_examples": len(entries),
        "kept_examples": len(rows),
        "skipped_breakdown": skipped,
        "train_count": len(training),
        "validation_count": len(validation),
        "tokens_all_rows": tok_total,
        "tokens_train_only_per_epoch": training_tokens_per_epoch,
        "epochs": epochs,
        "billed_training_tokens": billed_tokens,
        "estimated_cost_usd": round(estimated_cost, 2),
        "model_target": "gemini-2.5-flash",
        "system_instruction_chars": len(SYSTEM_INSTRUCTION),
        "distinct_contacts": len(per_contact),
    }

    print()
    print("=" * 60)
    print("COST & TOKEN ESTIMATE")
    print("=" * 60)
    print(f"  Train examples:            {summary['train_count']}")
    print(f"  Validation examples:       {summary['validation_count']}")
    print(f"  Tokens (all rows):         {summary['tokens_all_rows']:,}")
    print(f"  Tokens (train × {epochs} epochs):  "
          f"{summary['billed_training_tokens']:,}")
    print(f"  Target model:              {summary['model_target']}")
    print(f"  Price:                     ${price_per_m_2_5_flash:.2f} / 1M tokens")
    print(f"  Estimated training cost:   ${summary['estimated_cost_usd']}")
    print("=" * 60)

    if dry_run:
        print("\n[build] DRY RUN — skipping file writes.")
        return summary, training, validation

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Write training JSONL (validation goes to a separate file)
    train_path = OUT_DIR / "wingman_finetune_train.jsonl"
    val_path = OUT_DIR / "wingman_finetune_val.jsonl"
    with train_path.open("w", encoding="utf-8") as f:
        for row in training:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with val_path.open("w", encoding="utf-8") as f:
        for row in validation:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2))

    # Human-readable preview: 5 random examples, fully decoded
    preview_sample = rng.sample(training, min(5, len(training)))
    preview = []
    for row in preview_sample:
        preview.append({
            "system": row["systemInstruction"]["parts"][0]["text"],
            "user": row["contents"][0]["parts"][0]["text"],
            "model_output": row["contents"][1]["parts"][0]["text"],
        })
    OUT_PREVIEW.write_text(json.dumps(preview, indent=2, ensure_ascii=False))

    print(f"\n[build] Wrote:")
    print(f"         {train_path}  ({train_path.stat().st_size // 1024} KB)")
    print(f"         {val_path}    ({val_path.stat().st_size // 1024} KB)")
    print(f"         {OUT_SUMMARY}")
    print(f"         {OUT_PREVIEW}  <- inspect this BEFORE uploading")
    print()
    print("Next step: review the preview, then run upload script when ready.")

    return summary, training, validation


def main():
    ap = argparse.ArgumentParser(
        description="Build Vertex-AI JSONL from the Wingman Examples Library"
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="Compute stats but don't write any files")
    ap.add_argument("--split", type=float, default=0.05,
                    help="Fraction for validation set (default: 0.05)")
    ap.add_argument("--seed", type=int, default=42,
                    help="Shuffle seed (default: 42)")
    args = ap.parse_args()

    build(
        split=args.split,
        shuffle_seed=args.seed,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
