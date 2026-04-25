"""DeepSeek V4 Pro via Atlas Cloud — optional reply-generation backend.

Two modes, selected by ``deepseek_mode``:

  • ``normal``  — ships the Master Playbook + system prompt + chat
                  transcript (same context size as our current Pro
                  path). Fast, cheap, great quality.

  • ``full``    — ships the ENTIRE training corpus (~620k tokens) as a
                  stable prompt prefix. Cacheable at the API level so
                  repeated calls pay dramatically less. Slower first
                  call (~30-60s), fast subsequent calls thanks to
                  prefix caching.

Atlas Cloud speaks OpenAI-compat, so this client is a thin
``/chat/completions`` wrapper — mirrors ``kie_client.py`` and
``grok_client.py`` in shape so the rest of the pipeline doesn't care
which backend ran.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Awaitable, Callable

import httpx

ATLAS_BASE_URL = "https://api.atlascloud.ai/v1"
ATLAS_CHAT_URL = f"{ATLAS_BASE_URL}/chat/completions"

# Two variants — caller picks. "pro" has stronger reasoning, "flash"
# is faster for latency-sensitive flows. Both accept the same OpenAI-
# compat chat-completions request shape.
MODEL_ID_PRO = "deepseek-ai/deepseek-v4-pro"
MODEL_ID_FLASH = "deepseek-ai/deepseek-v4-flash"


def _resolve_model(variant: str) -> str:
    return MODEL_ID_FLASH if (variant or "").lower() == "flash" else MODEL_ID_PRO


def get_api_key() -> str:
    return (os.getenv("ATLASCLOUD_API_KEY") or "").strip()


def is_deepseek_configured() -> bool:
    return bool(get_api_key())


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
        messages.append({"role": "system", "content": system_instruction})
    # DeepSeek V4 Pro doesn't advertise multimodal support explicitly —
    # fall back to text-only if images are provided. (If a vision SKU
    # comes later, swap this to the multipart content array.)
    if images:
        # Include a hint in text that screenshots exist but can't be
        # parsed. Caller already has the transcript text so this is
        # just a fallback note.
        user_text = user_text + "\n\n(Note: screenshots accompany this chat but the model runs text-only.)"
    messages.append({"role": "user", "content": user_text})
    return messages


async def generate_deepseek_stream(
    system_instruction: str,
    user_text: str,
    images: list[bytes] | None = None,
    on_chunk: Callable[[str], Awaitable[None]] | None = None,
    temperature: float = 0.9,
    max_tokens: int = 8192,
    timeout_s: float = 180.0,
    api_key: str | None = None,
    cache_key: str | None = None,
    variant: str = "pro",
) -> str:
    """Stream a DeepSeek generation. Returns accumulated text in the
    same shape our existing JSON parser understands. ``variant``
    selects ``pro`` (deeper reasoning) or ``flash`` (faster)."""
    key = (api_key or get_api_key()).strip()
    if not key:
        raise RuntimeError(
            "ATLASCLOUD_API_KEY missing — add it to .env or toggle DeepSeek off"
        )

    model_id = _resolve_model(variant)
    payload = {
        "model": model_id,
        "messages": _build_messages(system_instruction, user_text, images),
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    # Atlas Cloud supports prompt caching on OpenAI-compat endpoints via
    # a conv-id-style header. Not strictly required but improves cache
    # hit rate when the system prompt is stable (full-training mode).
    if cache_key:
        headers["x-cache-key"] = cache_key

    accumulated = ""
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
        async with client.stream(
            "POST", ATLAS_CHAT_URL, headers=headers, json=payload,
        ) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise RuntimeError(
                    f"DeepSeek HTTP {resp.status_code}: "
                    f"{body.decode('utf-8', errors='replace')[:400]}"
                )
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    data = json.loads(data_str)
                except Exception:
                    continue
                choices = data.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content")
                if piece:
                    accumulated += piece
                    if on_chunk:
                        try:
                            await on_chunk(accumulated)
                        except Exception as cb_err:
                            print(f"[deepseek] chunk cb error: {cb_err}")
                # Log usage at end of stream if present (helps us verify
                # prefix caching is actually hitting)
                usage = data.get("usage")
                if usage and isinstance(usage, dict):
                    try:
                        tok = usage.get("prompt_tokens", 0)
                        cached = (usage.get("prompt_tokens_details") or {}).get(
                            "cached_tokens", 0
                        )
                        pct = (cached / tok * 100) if tok else 0
                        print(f"[deepseek] usage: input={tok:,} "
                              f"(cached={cached:,}, {pct:.0f}% hit)")
                    except Exception:
                        pass
    return accumulated
