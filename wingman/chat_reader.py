"""Chat extraction using Gemini 3.0 Flash.

Sends screenshots and/or videos to Gemini Flash in a SINGLE call so the
model sees the full conversation context across all media and returns
one unified transcript.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
from dataclasses import dataclass

from google import genai
from google.genai import types

from wingman.config import (
    GEMINI_API_KEY,
    FLASH_MODEL,
    CHAT_READER_PROMPT,
    CHAT_READER_BATCH_PROMPT,
)


@dataclass
class ChatReadResult:
    messages: list[dict]
    is_chat_visible: bool
    raw_response: str = ""


class ChatReader:
    """Extracts chat messages from screenshots/video using Gemini Flash."""

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
        """Read a single frame (used by live screen capture)."""
        if self._reading:
            return ChatReadResult(messages=[], is_chat_visible=False)

        self._reading = True
        try:
            client = self._get_client()
            image_part = types.Part.from_bytes(
                data=jpeg_bytes, mime_type="image/jpeg",
            )
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=FLASH_MODEL,
                contents=[CHAT_READER_PROMPT, image_part],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=16384,
                    response_mime_type="application/json",
                ),
            )
            result = self._parse(response.text)
            if result.is_chat_visible:
                print(f"[reader] Found {len(result.messages)} messages")
            return result
        except Exception as exc:
            print(f"[reader] Read failed: {exc}")
            return ChatReadResult(messages=[], is_chat_visible=False)
        finally:
            self._reading = False

    async def read_batch(self, media_items: list[tuple[bytes, str]]) -> ChatReadResult:
        """Read multiple screenshots/videos in ONE call.

        media_items: list of (data_bytes, mime_type) tuples.
        The model sees all media together and returns one unified transcript.
        """
        if not media_items:
            return ChatReadResult(messages=[], is_chat_visible=False)

        self._reading = True
        try:
            client = self._get_client()

            n_images = sum(1 for _, m in media_items if m.startswith("image/"))
            n_videos = sum(1 for _, m in media_items if m.startswith("video/"))
            print(f"[reader] Batch: {n_images} images, {n_videos} videos → single Gemini call")

            if len(media_items) == 1:
                prompt = CHAT_READER_PROMPT
            else:
                prompt = CHAT_READER_BATCH_PROMPT.format(count=len(media_items))

            contents: list = [prompt]
            for data, mime in media_items:
                contents.append(types.Part.from_bytes(data=data, mime_type=mime))

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=FLASH_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=65536,
                    response_mime_type="application/json",
                ),
            )

            result = self._parse(response.text)
            print(f"[reader] Batch result: {len(result.messages)} messages extracted")
            return result

        except Exception as exc:
            print(f"[reader] Batch read failed: {exc}")
            return ChatReadResult(messages=[], is_chat_visible=False)
        finally:
            self._reading = False

    @staticmethod
    def detect_mime(filename: str, data: bytes) -> str:
        """Guess MIME type from filename, with sensible defaults."""
        mime, _ = mimetypes.guess_type(filename)
        if mime:
            return mime
        if data[:4] == b'\xff\xd8\xff\xe0' or data[:4] == b'\xff\xd8\xff\xe1':
            return "image/jpeg"
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        if data[:4] == b'\x00\x00\x00\x1c' or data[:4] == b'\x00\x00\x00\x18':
            return "video/mp4"
        return "image/jpeg"

    @staticmethod
    def _parse(raw: str) -> ChatReadResult:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            print(f"[reader] Bad JSON:\n{raw[:300]}")
            return ChatReadResult(messages=[], is_chat_visible=False, raw_response=raw)

        if not isinstance(data, list):
            data = [data]

        messages: list[dict] = []
        for item in data:
            if isinstance(item, dict) and "text" in item:
                speaker = item.get("speaker", "them")
                if speaker not in ("me", "them"):
                    speaker = "them"
                msg: dict = {
                    "speaker": speaker,
                    "text": str(item["text"]).strip(),
                }
                if item.get("reply_to"):
                    msg["reply_to"] = str(item["reply_to"]).strip()
                messages.append(msg)

        return ChatReadResult(
            messages=messages,
            is_chat_visible=len(messages) > 0,
            raw_response=raw,
        )
