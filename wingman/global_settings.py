"""Tiny persistence for global runtime settings that aren't per-chat.

Currently holds:
  • ``global_extra_context`` — an optional directive the user locks
    across ALL chats (distinct from the per-chat lock stored in each
    chat's meta).
  • ``custom_reply_system_prompt`` — user override for the baseline
    'No goal' behavior. Empty string = use the hardcoded default from
    wingman/config.py. Set to a non-empty string to take over as the
    baseline for every call.

Lives in a single JSON file at the workspace root so it's easy to
inspect / edit manually if anything goes weird.
"""

from __future__ import annotations

import json
from pathlib import Path

SETTINGS_FILE = Path(__file__).parent.parent / "global_settings.json"


class GlobalSettings:
    def __init__(self):
        self.global_extra_context: str = ""
        self.custom_reply_system_prompt: str = ""
        self._load()

    def _load(self) -> None:
        if not SETTINGS_FILE.exists():
            return
        try:
            data = json.loads(SETTINGS_FILE.read_text()) or {}
            self.global_extra_context = (data.get("global_extra_context") or "").strip()
            self.custom_reply_system_prompt = (data.get("custom_reply_system_prompt") or "").strip()
        except Exception:
            # Corrupt file — start fresh, keep memory empty
            self.global_extra_context = ""
            self.custom_reply_system_prompt = ""

    def _save(self) -> None:
        try:
            SETTINGS_FILE.write_text(
                json.dumps(
                    {
                        "global_extra_context": self.global_extra_context,
                        "custom_reply_system_prompt": self.custom_reply_system_prompt,
                    },
                    indent=2,
                )
            )
        except Exception:
            pass

    def set_global_extra_context(self, value: str) -> None:
        self.global_extra_context = (value or "").strip()
        self._save()

    def set_custom_reply_system_prompt(self, value: str) -> None:
        """Persist a user-defined override for the baseline 'No goal'
        prompt. Empty / whitespace = revert to hardcoded default."""
        self.custom_reply_system_prompt = (value or "").strip()
        self._save()

    def refresh(self) -> None:
        """Re-read from disk. Cheap to call on every /api/state build."""
        self._load()
