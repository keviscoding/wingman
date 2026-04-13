"""Smart chat extraction using Gemini Flash vision.

Sends a screenshot to Gemini 2.5 Flash and gets back structured JSON
containing only the actual chat messages — no UI chrome, no browser tabs,
no buttons.  The model understands what a chat bubble looks like and who
sent each message.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from google import genai
from google.genai import types

from wingman.config import (
    GEMINI_API_KEY,
    FLASH_MODEL,
    CHAT_READER_PROMPT,
)


@dataclass
class ChatReadResult:
    messages: list[dict]  # [{"speaker": "me"|"them", "text": "..."}]
    is_chat_visible: bool
    raw_response: str = ""


class ChatReader:
    """Extracts chat messages from a screenshot using Gemini Flash vision."""

    def __init__(self):
        self._client: genai.Client | None = None
        self._reading = False

    def _get_client(self) -> genai.Client:
        if self._client is None:
            if not GEMINI_API_KEY:
                raise RuntimeError("GEMINI_API_KEY not set — add it to .env")
            self._client = genai.Client(
                api_key=GEMINI_API_KEY,
                http_options={"api_version": "v1beta"},
            )
        return self._client

    @property
    def is_busy(self) -> bool:
        return self._reading

    async def read(self, jpeg_bytes: bytes) -> ChatReadResult:
        """Analyze a screenshot and extract chat messages."""
        if self._reading:
            return ChatReadResult(messages=[], is_chat_visible=False)

        self._reading = True
        try:
            client = self._get_client()

            image_part = types.Part.from_bytes(
                data=jpeg_bytes,
                mime_type="image/jpeg",
            )

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=FLASH_MODEL,
                contents=[CHAT_READER_PROMPT, image_part],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=4096,
                    response_mime_type="application/json",
                ),
            )

            result = self._parse(response.text)
            if not result.is_chat_visible:
                print(f"[reader] No chat found (raw: {response.text[:80]})")
            else:
                print(f"[reader] Found {len(result.messages)} chat messages")
            return result

        except Exception as exc:
            print(f"[reader] Chat read failed: {exc}")
            return ChatReadResult(messages=[], is_chat_visible=False)
        finally:
            self._reading = False

    @staticmethod
    def _parse(raw: str) -> ChatReadResult:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            print(f"[reader] Bad JSON from Flash:\n{raw[:200]}")
            return ChatReadResult(messages=[], is_chat_visible=False, raw_response=raw)

        if not isinstance(data, list):
            data = [data]

        messages: list[dict] = []
        for item in data:
            if isinstance(item, dict) and "text" in item:
                speaker = item.get("speaker", "them")
                if speaker not in ("me", "them"):
                    speaker = "them"
                messages.append({
                    "speaker": speaker,
                    "text": str(item["text"]).strip(),
                })

        is_chat = len(messages) > 0
        return ChatReadResult(
            messages=messages,
            is_chat_visible=is_chat,
            raw_response=raw,
        )
