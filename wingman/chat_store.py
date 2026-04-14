"""Persistent chat storage — saves conversations by contact name.

Chats are stored as JSON files in a local directory. Each contact gets
their own file. New messages are appended, deduped against existing ones.
"""

from __future__ import annotations

import json
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

    def save(self, contact: str, messages: list[Message]):
        path = self._path(contact)
        data = {
            "contact": contact,
            "messages": [m.to_dict() for m in messages],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def save_raw(self, contact: str, messages: list[dict]):
        """Save messages that are already dicts (not Message objects)."""
        path = self._path(contact)
        data = {
            "contact": contact,
            "messages": messages,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def delete(self, contact: str):
        path = self._path(contact)
        if path.exists():
            path.unlink()
