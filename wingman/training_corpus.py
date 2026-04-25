"""Full training corpus loader — every transcript, concatenated.

For models with 2M+ context and prompt caching (Grok 4.20 multi-agent /
reasoning), we send ALL the training transcripts on every reply
generation. The first call pays the full prefix cost; every subsequent
call with the same stable prefix is served from xAI's cache at ~10% the
normal token price.

Why bother when we already have the Master Playbook?
    The playbook is Flash's *interpretation* of the transcripts (9k
    chars). The full corpus is 2.4M chars of actual Alex examples —
    tone, voice, exact phrasings, recovery patterns, escalation arcs,
    failure cases. Giving the model the raw material means it can
    pattern-match against real conversations rather than relying on a
    distilled summary that might have lost nuance.

The returned string is stable across runs (files sorted, hashed, cached
so xAI's cache prefix stays consistent).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

CORPUS_DIR = Path(__file__).parent.parent / "training"
CACHE_PATH = CORPUS_DIR / ".full_corpus.json"
VALID_SUFFIXES = {".txt", ".md", ".srt", ".vtt", ".text", ".csv"}

_HEADER = (
    "BEGIN TRAINING CORPUS — FULL TRANSCRIPTS\n"
    "The following {n} documents are the complete training material for "
    "replicating Alex's voice and frameworks. Study the patterns, tone, "
    "escalations, recoveries, and close moves. When generating replies "
    "below, pattern-match against these examples — especially in tone, "
    "word choice, and timing. Do NOT quote these back to the user; "
    "internalize and adapt.\n"
    "=" * 70
)

_FOOTER = "\n" + "=" * 70 + "\nEND TRAINING CORPUS"

_FILE_HEADER_FMT = "\n\n### DOCUMENT {idx}/{n}: {name}\n" + "-" * 60 + "\n"


def _read_files() -> list[tuple[str, str]]:
    """Return [(filename, text)] for all training docs, sorted by name
    so the corpus is byte-identical across runs (critical for caching)."""
    if not CORPUS_DIR.exists():
        return []
    out: list[tuple[str, str]] = []
    for f in sorted(CORPUS_DIR.iterdir()):
        if not f.is_file():
            continue
        if f.name.startswith("."):
            continue
        if f.suffix.lower() not in VALID_SUFFIXES:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            continue
        if text:
            out.append((f.name, text))
    return out


def _compute_hash(files: list[tuple[str, str]]) -> str:
    """Hash of (name, text) pairs so we can tell when the corpus changed."""
    h = hashlib.sha256()
    for name, text in files:
        h.update(name.encode("utf-8"))
        h.update(b"\x00")
        h.update(text.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def build_corpus_text() -> tuple[str, str, int]:
    """Build (or return cached) corpus string. Returns (text, hash, file_count).

    Empty tuple (``"", "", 0``) if the training folder is missing or empty."""
    files = _read_files()
    if not files:
        return "", "", 0

    current_hash = _compute_hash(files)

    # Return from on-disk cache when hash matches — saves rebuilding the
    # multi-MB string on every startup.
    if CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text())
            if cached.get("hash") == current_hash and cached.get("text"):
                return cached["text"], current_hash, cached.get("file_count", len(files))
        except Exception:
            pass

    parts: list[str] = [_HEADER.format(n=len(files))]
    n = len(files)
    for idx, (name, text) in enumerate(files, start=1):
        parts.append(_FILE_HEADER_FMT.format(idx=idx, n=n, name=name))
        parts.append(text)
    parts.append(_FOOTER)
    text_out = "\n".join(parts)

    try:
        CACHE_PATH.write_text(json.dumps({
            "hash": current_hash,
            "file_count": len(files),
            "char_count": len(text_out),
            "text": text_out,
        }, ensure_ascii=False))
    except Exception as exc:
        print(f"[corpus] Failed to cache corpus: {exc}")

    return text_out, current_hash, len(files)


class TrainingCorpus:
    """Lazy-loading wrapper. First ``text`` access reads/builds the cache."""

    def __init__(self):
        self._text: str = ""
        self._hash: str = ""
        self._file_count: int = 0
        self._loaded: bool = False

    def load(self) -> None:
        if self._loaded:
            return
        text, h, n = build_corpus_text()
        self._text = text
        self._hash = h
        self._file_count = n
        self._loaded = True
        if text:
            est_tokens = len(text) // 4
            print(f"[corpus] Loaded full training corpus: {n} files, "
                  f"{len(text):,} chars (~{est_tokens:,} tokens)")
        else:
            print("[corpus] No training files found — full-corpus mode will be a no-op")

    @property
    def text(self) -> str:
        if not self._loaded:
            self.load()
        return self._text

    @property
    def hash(self) -> str:
        if not self._loaded:
            self.load()
        return self._hash

    @property
    def file_count(self) -> int:
        if not self._loaded:
            self.load()
        return self._file_count

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def is_empty(self) -> bool:
        return not self.text
