"""Transcript builder with deduplication and reply-to support."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from thefuzz import fuzz

_DEDUP_THRESHOLD = 80
_MAX_MESSAGES = 200


@dataclass
class Message:
    speaker: str
    text: str
    reply_to: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        d = {"speaker": self.speaker, "text": self.text}
        if self.reply_to:
            d["reply_to"] = self.reply_to
        return d


@dataclass
class ConversationState:
    messages: list[Message] = field(default_factory=list)
    new_since_last_generation: int = 0

    def ingest_parsed_messages(self, parsed: list[dict]) -> int:
        added = 0
        for item in parsed:
            text = item.get("text", "").strip()
            if not text:
                continue
            speaker = item.get("speaker", "them")
            if speaker not in ("me", "them"):
                speaker = "them"
            reply_to = item.get("reply_to", "").strip()
            if not self._is_duplicate(text):
                self.messages.append(Message(
                    speaker=speaker, text=text, reply_to=reply_to,
                ))
                added += 1

        if len(self.messages) > _MAX_MESSAGES:
            self.messages = self.messages[-_MAX_MESSAGES:]

        self.new_since_last_generation += added
        return added

    def to_json(self, last_n: int | None = None) -> str:
        msgs = self.messages[-(last_n or len(self.messages)):]
        return json.dumps([m.to_dict() for m in msgs], ensure_ascii=False, indent=2)

    def to_display_list(self, last_n: int = 50) -> list[dict]:
        return [m.to_dict() for m in self.messages[-last_n:]]

    def mark_generation_done(self):
        self.new_since_last_generation = 0

    @property
    def has_pending_messages(self) -> bool:
        return self.new_since_last_generation > 0

    def _is_duplicate(self, text: str) -> bool:
        clean = text.strip()
        for existing in self.messages[-30:]:
            if fuzz.ratio(clean, existing.text) >= _DEDUP_THRESHOLD:
                return True
        return False
