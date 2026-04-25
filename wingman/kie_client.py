"""KIE AI proxy client — optional alternative to direct Google for Pro.

Lives behind the ``use_kie`` toggle. When off (default) everything keeps
going through google-genai directly. When on, Pro reply generations
route through KIE's OpenAI-compatible endpoint instead.

Keeps the same output shape as our direct Gemini calls (streaming, text
accumulated, on_chunk callback) so the rest of the pipeline (JSON
parsing, 3-tier safe-framing retry, reply persistence, UI streaming)
stays identical. Only the HTTP layer changes.

OpenAI-compat format:
  POST https://api.kie.ai/gemini-3.1-pro/v1/chat/completions
  Authorization: Bearer $KIE_API_KEY
  body: {messages:[{role,content}], stream:true, reasoning_effort:"high"}

This module is pure HTTP (httpx) — deliberately NOT using google-genai —
because KIE speaks OpenAI Chat Completions, not Gemini native.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Awaitable, Callable

import httpx

KIE_URL = "https://api.kie.ai/gemini-3.1-pro/v1/chat/completions"


def get_kie_api_key() -> str:
    return os.getenv("KIE_API_KEY", "").strip()


def is_kie_configured() -> bool:
    return bool(get_kie_api_key())


def _image_to_data_url(img_bytes: bytes) -> str:
    b64 = base64.b64encode(img_bytes).decode()
    return f"data:image/jpeg;base64,{b64}"


def _build_messages(
    system_instruction: str,
    user_text: str,
    images: list[bytes] | None,
) -> list[dict]:
    messages: list[dict] = []
    if system_instruction:
        # OpenAI-compat: system content can be a string or array. KIE
        # accepts array-of-parts shape consistently for both roles.
        messages.append({
            "role": "system",
            "content": [{"type": "text", "text": system_instruction}],
        })
    user_content: list[dict] = [{"type": "text", "text": user_text}]
    for img in (images or [])[:3]:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": _image_to_data_url(img)},
        })
    messages.append({"role": "user", "content": user_content})
    return messages


async def generate_kie_stream(
    system_instruction: str,
    user_text: str,
    images: list[bytes] | None = None,
    on_chunk: Callable[[str], Awaitable[None]] | None = None,
    reasoning_effort: str = "high",
    timeout_s: float = 120.0,
    api_key: str | None = None,
) -> str:
    """Stream a Pro generation through KIE. Returns the full accumulated
    text (same contract as our direct Gemini stream readers, so the JSON
    parser and retry layers downstream don't care which backend ran).

    Raises ``RuntimeError`` on missing key or non-200 HTTP. Raises
    ``asyncio.TimeoutError`` if the stream exceeds ``timeout_s``.
    """
    key = (api_key or get_kie_api_key()).strip()
    if not key:
        raise RuntimeError("KIE_API_KEY not set — add it to .env or toggle KIE off")

    payload = {
        "messages": _build_messages(system_instruction, user_text, images),
        "stream": True,
        "reasoning_effort": reasoning_effort,
        "include_thoughts": False,
    }

    accumulated = ""
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
        async with client.stream(
            "POST", KIE_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
        ) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise RuntimeError(
                    f"KIE HTTP {resp.status_code}: {body.decode('utf-8', errors='replace')[:400]}"
                )
            async for line in resp.aiter_lines():
                if not line:
                    continue
                # SSE frames look like "data: {...}" (or "data:{...}") and
                # a terminating "data: [DONE]".
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    data = json.loads(data_str)
                except Exception:
                    # KIE occasionally emits comment / heartbeat frames —
                    # ignore anything that isn't valid JSON.
                    continue
                choices = data.get("choices") or []
                if not choices:
                    continue
                # OpenAI stream deltas: choices[0].delta.content
                delta = choices[0].get("delta") or {}
                piece = delta.get("content")
                if piece:
                    accumulated += piece
                    if on_chunk:
                        try:
                            await on_chunk(accumulated)
                        except Exception as cb_err:
                            print(f"[kie] chunk callback error: {cb_err}")
    return accumulated


async def generate_kie_nonstream(
    system_instruction: str,
    user_text: str,
    images: list[bytes] | None = None,
    reasoning_effort: str = "high",
    timeout_s: float = 120.0,
    api_key: str | None = None,
) -> str:
    """Non-streaming version — used for the safe-framing retry tier
    where we don't need progressive delivery (just a final response)."""
    key = (api_key or get_kie_api_key()).strip()
    if not key:
        raise RuntimeError("KIE_API_KEY not set")

    payload = {
        "messages": _build_messages(system_instruction, user_text, images),
        "stream": False,
        "reasoning_effort": reasoning_effort,
        "include_thoughts": False,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
        resp = await client.post(
            KIE_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"KIE HTTP {resp.status_code}: {resp.text[:400]}"
            )
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        return (choices[0].get("message") or {}).get("content", "") or ""
