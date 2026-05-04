"""Load the hand-curated marketing training corpus.

The 28 viral-style transcripts in ``MARKETING TRAINING CHATS/`` are
what taught us what "works" — the escalation arc, the wordplay, the
pushback-then-fold pattern. We don't parse them into structured
objects because:

  1. The model we call (Gemini 3.1 Pro) handles raw text fine.
  2. Parsing would lose signal — the "[Context: ...]" tags and
     the mixed punctuation and the untidy line breaks are all
     part of the pattern we want the model to learn.
  3. Fewer moving parts = fewer places to break.

Instead we just read the two txt files, glue them, and hand the
string to the prompt builder as a few-shot block.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

CORPUS_DIR = Path(__file__).resolve().parent.parent / "MARKETING TRAINING CHATS"
CORPUS_FILES: tuple[str, ...] = ("training data 1.txt", "training data 2.txt")


def load_raw_corpus() -> str:
    """Return every training transcript, concatenated, as one big
    string ready to paste into a system prompt.

    Lightweight normalization only: strip trailing whitespace on
    each line and collapse 3+ blank lines to 2. Keep everything
    else untouched — the messy patterns are features, not bugs.
    """
    parts: list[str] = []
    for name in CORPUS_FILES:
        p = CORPUS_DIR / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        parts.append(_normalize(text))
    return "\n\n".join(parts).strip()


def _normalize(text: str) -> str:
    lines = [ln.rstrip() for ln in text.splitlines()]
    out: list[str] = []
    blanks = 0
    for ln in lines:
        if ln == "":
            blanks += 1
            if blanks <= 2:
                out.append("")
        else:
            blanks = 0
            out.append(ln)
    return "\n".join(out).strip()


def iter_transcript_blocks(raw: str) -> Iterable[str]:
    """Yield each transcript as its own block. Handles both file
    formats: "=== Conversation N: Title ===" markers (training 1)
    and "Transcript N:" markers (training 2).

    Used by few-shot samplers when we want to pick a subset instead
    of passing the entire corpus (e.g., to keep context window
    lean for cheaper generations).
    """
    current: list[str] = []
    for line in raw.splitlines():
        is_header = (
            line.startswith("=== Conversation")
            or line.startswith("Transcript ")
        )
        if is_header and current:
            block = "\n".join(current).strip()
            if block:
                yield block
            current = [line]
        else:
            current.append(line)
    if current:
        tail = "\n".join(current).strip()
        if tail:
            yield tail
