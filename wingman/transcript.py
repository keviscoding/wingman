"""Transcript builder with sequence-aware deduplication and reply-to support."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from thefuzz import fuzz

_DEDUP_THRESHOLD = 78
# Upper bound on in-memory conversation length. The summarizer compresses
# older messages before they ever hit the Pro prompt, so this limit is
# really just a safety rail against pathological growth. Override with
# WINGMAN_MAX_MESSAGES in .env if you keep longer threads.
try:
    _MAX_MESSAGES = max(500, int(os.getenv("WINGMAN_MAX_MESSAGES", "5000")))
except ValueError:
    _MAX_MESSAGES = 5000


@dataclass
class Message:
    speaker: str
    text: str
    reply_to: str = ""
    timestamp: float = 0.0
    time_label: str = ""  # human-readable from screenshot, e.g. "2:34 PM" or "Yesterday 6:12 PM"

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        d = {"speaker": self.speaker, "text": self.text}
        if self.reply_to:
            d["reply_to"] = self.reply_to
        if self.time_label:
            d["time"] = self.time_label
        return d


@dataclass
class ConversationState:
    messages: list[Message] = field(default_factory=list)
    new_since_last_generation: int = 0

    def ingest_parsed_messages(self, parsed: list[dict]) -> int:
        """Ingest a batch of parsed messages with sequence-aware dedup.

        Tries to find where the incoming batch overlaps with the existing
        conversation (tail matching), then only appends messages that come
        after the overlap. Falls back to per-message fuzzy dedup.
        """
        incoming = []
        for item in parsed:
            text = item.get("text", "").strip()
            if not text:
                continue
            speaker = item.get("speaker", "them")
            if speaker not in ("me", "them"):
                speaker = "them"
            reply_to = item.get("reply_to", "").strip()
            time_label = item.get("time", "").strip()
            incoming.append(Message(speaker=speaker, text=text, reply_to=reply_to, time_label=time_label))

        if not incoming:
            return 0

        if not self.messages:
            self.messages.extend(incoming)
            self.new_since_last_generation += len(incoming)
            self._trim()
            return len(incoming)

        # Try sequence overlap: find the latest message in `incoming`
        # that matches something near the end of `self.messages`.
        # Everything AFTER that overlap point in `incoming` is new.
        new_start = self._find_overlap(incoming)

        if new_start is not None:
            new_msgs = incoming[new_start:]
        else:
            # No sequence overlap found — fall back to individual dedup
            new_msgs = [m for m in incoming if not self._is_duplicate(m.text)]

        if new_msgs:
            self.messages.extend(new_msgs)
            self.new_since_last_generation += len(new_msgs)
            self._trim()

        return len(new_msgs)

    def _find_overlap(self, incoming: list[Message]) -> int | None:
        """Find where `incoming` overlaps with the tail of existing messages.

        Scans incoming messages backwards, looking for a match against
        the last ~50 existing messages. Returns the index in `incoming`
        where new (non-overlapping) messages start, or None if no clear
        overlap is found.

        Example:
          existing: [A, B, C, D, E]
          incoming: [C, D, E, F, G]
          → overlap at D,E → returns index 3 (F is first new message)
        """
        existing_tail = self.messages[-50:]

        # Try to match the LAST incoming message that exists in our conversation.
        # Walk backwards through incoming to find the deepest overlap.
        best_incoming_idx = -1
        for i in range(len(incoming) - 1, -1, -1):
            for j in range(len(existing_tail) - 1, -1, -1):
                if self._msgs_match(incoming[i], existing_tail[j]):
                    # Found a match. Verify sequence: check that surrounding
                    # messages also match (at least 1 neighbor) to avoid
                    # false positives from common short messages like "ok" / "lol".
                    if self._verify_sequence(incoming, i, existing_tail, j):
                        best_incoming_idx = i
                        break
            if best_incoming_idx >= 0:
                break

        if best_incoming_idx < 0:
            return None

        new_start = best_incoming_idx + 1
        if new_start >= len(incoming):
            return new_start  # all incoming messages already exist

        return new_start

    def _verify_sequence(
        self,
        incoming: list[Message], i_idx: int,
        existing: list[Message], e_idx: int,
    ) -> bool:
        """Verify an overlap match by checking at least one neighbor also matches."""
        # Check the message before
        if i_idx > 0 and e_idx > 0:
            if self._msgs_match(incoming[i_idx - 1], existing[e_idx - 1]):
                return True
        # Check the message after
        if i_idx < len(incoming) - 1 and e_idx < len(existing) - 1:
            if self._msgs_match(incoming[i_idx + 1], existing[e_idx + 1]):
                return True
        # If it's a long-ish message (>20 chars), a single match is enough
        if len(incoming[i_idx].text) > 20:
            return True
        # Short messages like "ok", "lol" need a neighbor match
        return False

    @staticmethod
    def _msgs_match(a: Message, b: Message) -> bool:
        """Check if two messages are the same (fuzzy text + same speaker)."""
        if a.speaker != b.speaker:
            return False
        return fuzz.ratio(a.text.strip(), b.text.strip()) >= _DEDUP_THRESHOLD

    def to_json(self, last_n: int | None = None) -> str:
        msgs = self.messages[-(last_n or len(self.messages)):]
        return json.dumps([m.to_dict() for m in msgs], ensure_ascii=False, indent=2)

    def to_display_list(self, last_n: int | None = None) -> list[dict]:
        msgs = self.messages if last_n is None else self.messages[-last_n:]
        return [m.to_dict() for m in msgs]

    def mark_generation_done(self):
        self.new_since_last_generation = 0

    @property
    def has_pending_messages(self) -> bool:
        return self.new_since_last_generation > 0

    def _is_duplicate(self, text: str) -> bool:
        """Fallback per-message dedup — checks ALL existing messages."""
        clean = text.strip()
        for existing in self.messages:
            if fuzz.ratio(clean, existing.text) >= _DEDUP_THRESHOLD:
                return True
        return False

    def time_context(self) -> str:
        """Lightweight time context — just current time and who spoke last."""
        from datetime import datetime

        if not self.messages:
            return ""

        now = datetime.now()
        last = self.messages[-1]

        parts = [
            f"Current date/time: {now.strftime('%A %B %d, %Y, %I:%M %p')}",
            f"Last message was from: {'me' if last.speaker == 'me' else 'them'}",
        ]

        if last.time_label:
            parts.append(f"Last message timestamp (from chat): {last.time_label}")

        return "TIME CONTEXT:\n- " + "\n- ".join(parts)

    @staticmethod
    def _format_gap(seconds: float) -> str:
        if seconds < 0:
            return "just now"
        if seconds < 60:
            return f"{int(seconds)} seconds"
        if seconds < 3600:
            return f"{int(seconds / 60)} minutes"
        if seconds < 86400:
            h = seconds / 3600
            return f"{h:.1f} hours" if h < 10 else f"{int(h)} hours"
        days = seconds / 86400
        return f"{days:.1f} days" if days < 7 else f"{int(days)} days"

    def _trim(self):
        if len(self.messages) > _MAX_MESSAGES:
            self.messages = self.messages[-_MAX_MESSAGES:]
