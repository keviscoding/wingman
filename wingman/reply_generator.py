"""Gemini 3.1 Pro reply generation with training context cache.

Uses the cached training transcripts (if loaded) so every reply is
informed by the text game knowledge. Also includes the user's spoken
goal/intent for the specific chat.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from google import genai
from google.genai import types

from wingman.config import (
    GEMINI_API_KEY,
    PRO_MODEL,
    REPLY_SYSTEM_PROMPT,
    DEFAULT_STYLE,
)


@dataclass
class ReplyOption:
    label: str
    text: str
    why: str = ""

    def to_dict(self) -> dict:
        d = {"label": self.label, "text": self.text}
        if self.why:
            d["why"] = self.why
        return d


@dataclass
class GenerationResult:
    replies: list[ReplyOption]
    read: str = ""
    advice: str = ""


class ReplyGenerator:
    def __init__(self):
        self._client: genai.Client | None = None
        self._style: str = DEFAULT_STYLE
        self._generating = False
        self._cache_name: str | None = None

    def set_cache(self, cache_name: str | None):
        self._cache_name = cache_name

    def _get_client(self) -> genai.Client:
        if self._client is None:
            if not GEMINI_API_KEY:
                raise RuntimeError("GEMINI_API_KEY not set")
            self._client = genai.Client(api_key=GEMINI_API_KEY)
        return self._client

    @property
    def style(self) -> str:
        return self._style

    @style.setter
    def style(self, value: str):
        self._style = value or DEFAULT_STYLE

    @property
    def is_busy(self) -> bool:
        return self._generating

    async def generate(
        self,
        transcript_json: str,
        extra_context: str = "",
        goal: str = "",
    ) -> GenerationResult:
        if self._generating:
            return GenerationResult(replies=[])

        self._generating = True
        try:
            prompt = REPLY_SYSTEM_PROMPT.format(
                transcript=transcript_json,
            )
            if goal:
                prompt += f"\n\nMy goal for this chat: {goal}"
            if extra_context:
                prompt += f"\n\nAdditional context: {extra_context}"

            config = types.GenerateContentConfig(
                temperature=0.9,
                max_output_tokens=4096,
            )
            if self._cache_name:
                config.cached_content = self._cache_name

            client = self._get_client()
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=PRO_MODEL,
                contents=prompt,
                config=config,
            )

            return self._parse_response(response.text)
        except Exception as exc:
            print(f"[pro] Reply generation failed: {exc}")
            return GenerationResult(replies=[])
        finally:
            self._generating = False

    @staticmethod
    def _parse_response(raw: str) -> GenerationResult:
        import re
        text = raw.strip()

        # Try to find JSON object in the response (model may wrap it in markdown)
        json_match = re.search(r'\{[\s\S]*\}', text)
        if not json_match:
            # No JSON found — return the whole response as the "read"
            print("[pro] No JSON in response, treating as freeform")
            return GenerationResult(replies=[], read=text, advice="")

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            print(f"[pro] Bad JSON, treating as freeform")
            return GenerationResult(replies=[], read=text, advice="")

        read = ""
        advice = ""
        replies_data = []

        if isinstance(data, dict):
            read = data.get("read", "")
            advice = data.get("advice", "")
            replies_data = data.get("replies", [])
        elif isinstance(data, list):
            replies_data = data

        replies = [
            ReplyOption(
                label=item.get("label", "option"),
                text=item["text"],
                why=item.get("why", ""),
            )
            for item in replies_data[:10]
            if isinstance(item, dict) and "text" in item
        ]

        return GenerationResult(replies=replies, read=read, advice=advice)
