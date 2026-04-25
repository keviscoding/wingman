"""Master Playbook extraction from training transcripts.

Reads all training files ONCE at startup, uses Flash to distill them into a
dense ~15-20k token coaching playbook. This playbook goes into the system
prompt of every reply generation call — no RAG retrieval, no per-request
embedding overhead, no context cache. Just pure concentrated knowledge.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from wingman.config import make_genai_client, FLASH_MODEL

TRAINING_DIR = Path(__file__).parent.parent / "training"
PLAYBOOK_CACHE_PATH = TRAINING_DIR / ".master_playbook.json"

PLAYBOOK_PROMPT = (
    "You are analyzing text game coaching transcripts from the 'Playing With Fire' series by Alex. "
    "Read ALL the transcripts below and produce a MASTER PLAYBOOK — a dense, comprehensive "
    "coaching reference (aim for 3000-4000 words) that another AI can use as its system prompt "
    "to perfectly replicate Alex's coaching style and expertise.\n\n"
    "The playbook MUST cover:\n\n"
    "## IDENTITY & TONE\n"
    "- Who is the coach? Persona, tone, energy, attitude\n"
    "- How replies should sound (length, emoji patterns, punctuation, vibe)\n"
    "- What makes Alex's style different from generic dating advice\n\n"
    "## CORE PRINCIPLES\n"
    "- Frame control, investment theory, push-pull dynamics\n"
    "- Takeaways (mild, medium, hard) — when and how to use each\n"
    "- Pings, disqualifications, compliance tests\n"
    "- The '2/3 rule', matching energy, never over-investing\n\n"
    "## SITUATION PLAYBOOK\n"
    "For each situation, give the EXACT strategy + example texts:\n"
    "- Openers (Tinder, Hinge, Instagram DMs, cold approach follow-ups)\n"
    "- Building investment / getting her hooked\n"
    "- Handling flakes and ghosting\n"
    "- Shit tests and frame challenges\n"
    "- Escalation and sexualization\n"
    "- Logistics and date closes\n"
    "- Re-engagement after going cold\n"
    "- When she's very interested vs lukewarm vs pulling away\n\n"
    "## RULES (ALWAYS / NEVER)\n"
    "- List every concrete rule from the transcripts\n"
    "- Include specific 'If she does X, you do Y' patterns\n\n"
    "## EXAMPLE TEXTS\n"
    "- Include 20-30 actual example reply texts from the transcripts, categorized by situation\n"
    "- Show the exact wording, emoji usage, and energy level\n\n"
    "Write it as DIRECT INSTRUCTIONS to an AI: 'You always...', 'Never...', "
    "'When she does X, you respond with...'. Be EXTREMELY specific — use exact "
    "phrasing and examples from the transcripts. No vague advice. No filler.\n\n"
    "TRANSCRIPTS:\n{text}"
)


class TrainingRAG:
    """Generates and caches a Master Playbook from training transcripts."""

    def __init__(self):
        self._client = None
        self._playbook: str = ""
        self._file_hash: str | None = None
        self.status: str = "not loaded"
        self.file_count: int = 0

    def _get_client(self):
        if self._client is None:
            self._client = make_genai_client()
        return self._client

    def _list_training_files(self) -> list[Path]:
        if not TRAINING_DIR.exists():
            TRAINING_DIR.mkdir(parents=True, exist_ok=True)
            return []
        exts = {".txt", ".md", ".text", ".csv", ".json", ".srt", ".vtt"}
        return [f for f in sorted(TRAINING_DIR.iterdir())
                if f.suffix.lower() in exts and f.is_file() and not f.name.startswith(".")]

    def _compute_hash(self, files: list[Path]) -> str:
        h = hashlib.sha256()
        for f in files:
            h.update(f.name.encode())
            h.update(str(f.stat().st_mtime).encode())
            h.update(str(f.stat().st_size).encode())
        return h.hexdigest()[:16]

    def load(self) -> bool:
        files = self._list_training_files()
        if not files:
            self.status = "no files"
            print(f"[playbook] No training files in {TRAINING_DIR}/")
            return False

        file_hash = self._compute_hash(files)
        if file_hash == self._file_hash and self._playbook:
            return True

        self.file_count = len(files)
        self.status = "loading"

        cached = self._load_cached_playbook(file_hash)
        if cached:
            self._playbook = cached
            self._file_hash = file_hash
            self.status = "loaded"
            print(f"[playbook] Loaded cached playbook ({len(self._playbook):,} chars)")
            return True

        print(f"[playbook] Reading {len(files)} training files...")
        all_text = self._read_all_files(files)
        if not all_text:
            self.status = "no readable files"
            return False

        print(f"[playbook] Generating Master Playbook from {len(files)} files (one-time, ~30s)...")
        t0 = time.time()
        playbook = self._generate_playbook(all_text)
        if not playbook:
            self.status = "generation failed"
            return False

        self._playbook = playbook
        self._file_hash = file_hash
        self._save_cached_playbook(file_hash, playbook)
        self.status = "loaded"
        elapsed = time.time() - t0
        print(f"[playbook] Master Playbook ready: {len(playbook):,} chars in {elapsed:.1f}s")
        return True

    def _read_all_files(self, files: list[Path]) -> str:
        parts = []
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                parts.append(f"--- {f.name} ---\n{text}\n")
            except Exception as exc:
                print(f"[playbook] Skipped {f.name}: {exc}")
        return "\n".join(parts)

    def _generate_playbook(self, all_text: str) -> str:
        client = self._get_client()
        try:
            from google.genai import types
            response = client.models.generate_content(
                model=FLASH_MODEL,
                contents=PLAYBOOK_PROMPT.format(text=all_text),
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=8192,
                ),
            )
            return response.text.strip()
        except Exception as exc:
            print(f"[playbook] Generation failed: {exc}")
            return ""

    def _load_cached_playbook(self, file_hash: str) -> str:
        if not PLAYBOOK_CACHE_PATH.exists():
            return ""
        try:
            data = json.loads(PLAYBOOK_CACHE_PATH.read_text())
            if data.get("hash") == file_hash:
                return data.get("playbook", "")
        except Exception:
            pass
        return ""

    def _save_cached_playbook(self, file_hash: str, playbook: str):
        try:
            PLAYBOOK_CACHE_PATH.write_text(json.dumps({
                "hash": file_hash,
                "playbook": playbook,
            }))
        except Exception as exc:
            print(f"[playbook] Could not save cache: {exc}")

    @property
    def knowledge_summary(self) -> str:
        return self._playbook

    def retrieve_examples(self, conversation_text: str, top_k: int = 3) -> str:
        """No longer does retrieval — playbook in system prompt is sufficient."""
        return ""
