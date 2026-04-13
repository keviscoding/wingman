"""Training data loader + Gemini context cache manager.

Reads transcript files from the training/ folder, uploads them into a
Gemini context cache that persists for 1 hour. The cache is referenced
by every Pro reply generation call so the model has the full text game
knowledge baked in.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from google import genai
from google.genai import types

from wingman.config import GEMINI_API_KEY, PRO_MODEL

TRAINING_DIR = Path(__file__).parent.parent / "training"
CACHE_TTL = "3600s"  # 1 hour

TRAINING_SYSTEM_INSTRUCTION = (
    "Watch these transcripts. Read them. Learn from the texting game in them. "
    "These are real chats that actually worked. Link it all together so you "
    "have the full context of what's happening in each one.\n\n"
    "Learn everything from it. Assimilate everything so you become a text game "
    "demon. Whatever I need, when I send you chats, you give perfect text game "
    "for every scenario.\n\n"
    "Read and assimilate EVERYTHING, EVERY SINGLE ONE OF THOSE FILES. "
    "You are the coach now."
)


class TrainingCache:
    """Manages loading training files and creating/refreshing the Gemini cache."""

    def __init__(self):
        self._client: genai.Client | None = None
        self._cache_name: str | None = None
        self._file_hash: str | None = None
        self._loaded_files: int = 0
        self._token_count: int = 0
        self.status: str = "not loaded"

    @property
    def cache_name(self) -> str | None:
        return self._cache_name

    @property
    def is_loaded(self) -> bool:
        return self._cache_name is not None

    @property
    def file_count(self) -> int:
        return self._loaded_files

    @property
    def token_count(self) -> int:
        return self._token_count

    def _get_client(self) -> genai.Client:
        if self._client is None:
            if not GEMINI_API_KEY:
                raise RuntimeError("GEMINI_API_KEY not set")
            self._client = genai.Client(api_key=GEMINI_API_KEY)
        return self._client

    def _list_training_files(self) -> list[Path]:
        if not TRAINING_DIR.exists():
            TRAINING_DIR.mkdir(parents=True, exist_ok=True)
            return []
        exts = {".txt", ".md", ".text", ".csv", ".json", ".srt", ".vtt"}
        files = [f for f in sorted(TRAINING_DIR.iterdir()) if f.suffix.lower() in exts and f.is_file()]
        return files

    def _compute_hash(self, files: list[Path]) -> str:
        h = hashlib.sha256()
        for f in files:
            h.update(f.name.encode())
            h.update(str(f.stat().st_mtime).encode())
            h.update(str(f.stat().st_size).encode())
        return h.hexdigest()[:16]

    def load(self) -> bool:
        """Load training files and create the Gemini context cache.

        Returns True if cache was created successfully.
        """
        files = self._list_training_files()
        if not files:
            self.status = "no files"
            print(f"[training] No training files found in {TRAINING_DIR}/")
            print(f"[training] Add .txt transcript files to get started")
            return False

        new_hash = self._compute_hash(files)
        if new_hash == self._file_hash and self._cache_name:
            self.status = "loaded (cached)"
            return True

        print(f"[training] Loading {len(files)} training files...")
        self.status = "loading"

        # Read all files into one big content block
        parts = []
        total_chars = 0
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                parts.append(f"--- {f.name} ---\n{text}\n\n")
                total_chars += len(text)
            except Exception as exc:
                print(f"[training] Skipped {f.name}: {exc}")

        if not parts:
            self.status = "no readable files"
            return False

        combined = "TRAINING TRANSCRIPTS:\n\n" + "".join(parts)
        print(f"[training] Total: {len(parts)} files, {total_chars:,} chars")

        # Delete old cache if exists
        if self._cache_name:
            try:
                self._get_client().caches.delete(name=self._cache_name)
            except Exception:
                pass

        try:
            client = self._get_client()
            cache = client.caches.create(
                model=PRO_MODEL,
                config=types.CreateCachedContentConfig(
                    display_name="wingman-training",
                    system_instruction=TRAINING_SYSTEM_INSTRUCTION,
                    contents=[types.Content(
                        role="user",
                        parts=[types.Part(text=combined)],
                    )],
                    ttl=CACHE_TTL,
                )
            )
            self._cache_name = cache.name
            self._file_hash = new_hash
            self._loaded_files = len(parts)
            self._token_count = cache.usage_metadata.total_token_count or 0
            self.status = "loaded"
            print(f"[training] Cache created: {self._token_count:,} tokens, "
                  f"{self._loaded_files} files, TTL {CACHE_TTL}")
            return True

        except Exception as exc:
            print(f"[training] Cache creation failed: {exc}")
            self.status = f"error: {exc}"
            return False

    def refresh_if_needed(self):
        """Check if files changed and refresh the cache."""
        files = self._list_training_files()
        if not files:
            return
        new_hash = self._compute_hash(files)
        if new_hash != self._file_hash:
            print("[training] Files changed, refreshing cache...")
            self.load()
