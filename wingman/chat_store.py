"""Persistent chat storage — saves conversations by contact name.

Chats are stored as JSON files in a local directory. Each contact gets
their own file. New messages are appended, deduped against existing ones.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from wingman.transcript import Message

STORE_DIR = Path(__file__).parent.parent / "chats"


class ChatStore:
    def __init__(self, store_dir: Path = STORE_DIR):
        self._dir = store_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip().lower()
        return self._dir / f"{safe}.json"

    def list_contacts(self) -> list[str]:
        contacts = []
        for f in sorted(self._dir.glob("*.json")):
            # Skip hidden/dotfile caches (e.g. .summary_*.json written by
            # the conversation summarizer). They aren't chats and should
            # never appear in the sidebar.
            if f.name.startswith("."):
                continue
            try:
                data = json.loads(f.read_text())
                contacts.append(data.get("contact", f.stem))
            except Exception:
                pass
        return contacts

    def load(self, contact: str) -> list[dict]:
        path = self._path(contact)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text())
            return data.get("messages", [])
        except Exception:
            return []

    def load_meta(self, contact: str) -> dict:
        """Load per-contact metadata (receptiveness, etc.)."""
        path = self._path(contact)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
            return data.get("meta", {})
        except Exception:
            return {}

    def save_meta(self, contact: str, meta: dict):
        """Update per-contact metadata without touching messages."""
        path = self._path(contact)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            data["meta"] = meta
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception:
            pass

    def _read_existing(self, path: Path) -> tuple[dict, list[dict]]:
        if not path.exists():
            return {}, []
        try:
            existing = json.loads(path.read_text())
            return existing.get("meta", {}) or {}, existing.get("messages", []) or []
        except Exception:
            return {}, []

    def _maybe_bump_activity(
        self, meta: dict, old_msgs: list[dict], new_msgs: list[dict]
    ) -> dict:
        """Set last_activity_at only when the message set actually changed
        (grew, shrunk, or last message text changed). Prevents stale-chat
        renames / no-op resaves from looking like new activity.
        """
        old_count = len(old_msgs)
        new_count = len(new_msgs)
        old_last = old_msgs[-1].get("text", "") if old_msgs else ""
        new_last = new_msgs[-1].get("text", "") if new_msgs else ""
        changed = (new_count != old_count) or (new_last != old_last)
        if changed and new_count > 0:
            meta["last_activity_at"] = time.time()
        return meta

    def save(self, contact: str, messages: list[Message]):
        path = self._path(contact)
        existing_meta, old_msgs = self._read_existing(path)
        new_msgs = [m.to_dict() for m in messages]
        existing_meta = self._maybe_bump_activity(existing_meta, old_msgs, new_msgs)
        data = {
            "contact": contact,
            "messages": new_msgs,
            "meta": existing_meta,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def save_raw(self, contact: str, messages: list[dict]):
        """Save messages that are already dicts (not Message objects)."""
        path = self._path(contact)
        existing_meta, old_msgs = self._read_existing(path)
        existing_meta = self._maybe_bump_activity(existing_meta, old_msgs, messages)
        data = {
            "contact": contact,
            "messages": messages,
            "meta": existing_meta,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def delete(self, contact: str):
        path = self._path(contact)
        if path.exists():
            path.unlink()
