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
        self._training_cache = None

    def set_cache(self, cache_name: str | None, training_cache=None):
        self._cache_name = cache_name
        if training_cache is not None:
            self._training_cache = training_cache

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

    def _build_prompt_and_config(self, transcript_json: str, extra_context: str, goal: str):
        prompt = REPLY_SYSTEM_PROMPT.format(transcript=transcript_json)
        if goal:
            prompt += f"\n\nMy goal for this chat: {goal}"
        if extra_context:
            prompt += f"\n\nAdditional context: {extra_context}"

        if self._training_cache:
            self._training_cache.ensure_valid()
            self._cache_name = self._training_cache.cache_name

        config = types.GenerateContentConfig(
            temperature=0.9,
                        max_output_tokens=4096,
        )
        if self._cache_name:
            config.cached_content = self._cache_name
        return prompt, config

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
            prompt, config = self._build_prompt_and_config(
                transcript_json, extra_context, goal,
            )

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    client = self._get_client()
                    response = await asyncio.to_thread(
                        client.models.generate_content,
                        model=PRO_MODEL,
                        contents=prompt,
                        config=config,
                    )
                    return self._parse_response(response.text)

                except Exception as exc:
                    err_str = str(exc)
                    is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                    is_cache_gone = "403" in err_str or "CachedContent not found" in err_str

                    if is_cache_gone and self._training_cache:
                        print(f"[pro] Cache expired, refreshing... (attempt {attempt+1})")
                        self._training_cache._file_hash = None
                        self._training_cache.load()
                        self._cache_name = self._training_cache.cache_name
                        prompt, config = self._build_prompt_and_config(
                            transcript_json, extra_context, goal,
                        )
                        continue

                    if is_rate_limit and attempt < max_retries - 1:
                        wait = (attempt + 1) * 15
                        print(f"[pro] Rate limited, waiting {wait}s... (attempt {attempt+1})")
                        await asyncio.sleep(wait)
                        continue

                    print(f"[pro] Reply generation failed: {exc}")
                    return GenerationResult(replies=[])

            return GenerationResult(replies=[])
        finally:
            self._generating = False

    async def generate_stream(
        self,
        transcript_json: str,
        extra_context: str = "",
        goal: str = "",
        on_chunk=None,
    ) -> GenerationResult:
        """Stream reply generation -- calls on_chunk(partial_text) as tokens arrive."""
        if self._generating:
            return GenerationResult(replies=[])

        self._generating = True
        try:
            prompt, config = self._build_prompt_and_config(
                transcript_json, extra_context, goal,
            )
            client = self._get_client()

            accumulated = ""

            def _stream():
                nonlocal accumulated
                for chunk in client.models.generate_content_stream(
                    model=PRO_MODEL,
                    contents=prompt,
                    config=config,
                ):
                    if chunk.text:
                        accumulated += chunk.text
                return accumulated

            full_text = await asyncio.to_thread(_stream)
            return self._parse_response(full_text)

        except Exception as exc:
            print(f"[pro] Stream generation failed: {exc}")
            if self._training_cache and ("403" in str(exc) or "CachedContent" in str(exc)):
                print("[pro] Cache expired during stream, falling back to non-stream...")
                self._generating = False
                self._training_cache._file_hash = None
                self._training_cache.load()
                self._cache_name = self._training_cache.cache_name
                return await self.generate(transcript_json, extra_context, goal)
            return GenerationResult(replies=[])
        finally:
            self._generating = False

    @staticmethod
    def _parse_response(raw: str) -> GenerationResult:
        import re
        text = raw.strip()

        # Strip markdown code fences (```json ... ``` or ``` ... ```)
        fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if fence_match:
            text = fence_match.group(1).strip()

        # Try to find JSON object in the response
        json_match = re.search(r'\{[\s\S]*\}', text)
        if not json_match:
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
