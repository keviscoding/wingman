"""xAI Grok 4.20 client — optional reply-generation backend.

Lives behind the ``use_grok`` toggle (mirrors KIE). When on, Pro reply
generations route through xAI's API instead of Google/Gemini. Off by
default so existing users keep their current behavior.

TWO MODES (controlled by ``grok_mode``):

• ``multi-agent`` (DEFAULT) — ``grok-4.20-multi-agent`` via the Responses
  API (``/v1/responses``). Runs Grok (coordinator) + Harper (research) +
  Benjamin (logic) + Lucas (contrarian/creative) in parallel BEFORE
  emitting output. Lucas is the key for writing quality: he stress-tests
  the other agents' drafts, spots bland/convergent answers, and enforces
  creative diversity. Best replies for the Wingman use case. Slower TTFT
  (10–30s while agents deliberate) but streams quickly once the leader
  synthesizes. ~$2/$6 per M input/output tokens.

• ``reasoning`` — ``grok-4.20-reasoning`` via the regular Chat
  Completions API. Single-agent, no Lucas, fast. Same price point. Good
  fallback when Multi-Agent is overloaded or when latency matters more
  than creative nuance. OpenAI-compatible shape — identical to our KIE
  pipeline, so the same JSON parser and retry tiers downstream don't
  care which ran.

Both paths accept the same signature as our Google / KIE streamers
(system_instruction + user_text + images + on_chunk), return the full
accumulated text, and raise on HTTP error so the caller can fall back.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Awaitable, Callable

import httpx

XAI_BASE_URL = "https://api.x.ai/v1"
XAI_CHAT_URL = f"{XAI_BASE_URL}/chat/completions"
XAI_RESPONSES_URL = f"{XAI_BASE_URL}/responses"

# Default model IDs. Aliases are stable per xAI docs.
MODEL_MULTI_AGENT = "grok-4.20-multi-agent"
MODEL_REASONING = "grok-4.20-reasoning"
MODEL_NON_REASONING = "grok-4.20-non-reasoning"  # kept for future fast-path


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def get_grok_api_key() -> str:
    """Return the xAI key from env. Supports both XAI_API_KEY (official
    xAI naming) and GROK_API_KEY (nicer for users who think of it by
    product name). XAI wins if both set."""
    return (os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY") or "").strip()


def is_grok_configured() -> bool:
    return bool(get_grok_api_key())


# ---------------------------------------------------------------------------
# Message / input builders (OpenAI-compatible shape)
# ---------------------------------------------------------------------------


def _image_to_data_url(img_bytes: bytes) -> str:
    b64 = base64.b64encode(img_bytes).decode()
    return f"data:image/jpeg;base64,{b64}"


def _build_user_content(user_text: str, images: list[bytes] | None) -> list[dict]:
    parts: list[dict] = [{"type": "text", "text": user_text}]
    for img in (images or [])[:3]:
        parts.append({
            "type": "image_url",
            "image_url": {"url": _image_to_data_url(img)},
        })
    return parts


def _build_chat_messages(
    system_instruction: str,
    user_text: str,
    images: list[bytes] | None,
) -> list[dict]:
    messages: list[dict] = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({
        "role": "user",
        "content": _build_user_content(user_text, images),
    })
    return messages


def _build_responses_input(
    system_instruction: str,
    user_text: str,
    images: list[bytes] | None,
) -> tuple[list[dict], str]:
    """Responses API takes ``input`` (list of role/content) + optional
    top-level ``instructions`` field for the system prompt. Returning
    both so the caller can set them on the request."""
    user_content = _build_user_content(user_text, images)
    # Responses API content parts use "input_text" / "input_image" types
    # (slightly different from chat-completions' "text" / "image_url").
    responses_parts: list[dict] = []
    for p in user_content:
        if p.get("type") == "text":
            responses_parts.append({"type": "input_text", "text": p["text"]})
        elif p.get("type") == "image_url":
            responses_parts.append({
                "type": "input_image",
                "image_url": p["image_url"]["url"],
            })
    input_blocks = [{"role": "user", "content": responses_parts}]
    return input_blocks, system_instruction or ""


# ---------------------------------------------------------------------------
# Streaming (multi-agent / Lucas path)
# ---------------------------------------------------------------------------


async def _generate_multi_agent_stream(
    system_instruction: str,
    user_text: str,
    images: list[bytes] | None,
    on_chunk: Callable[[str], Awaitable[None]] | None,
    agent_count: int,
    timeout_s: float,
    api_key: str,
    prompt_cache_key: str | None = None,
) -> str:
    """Stream through the Responses API with multi-agent orchestration.

    Wire format (SSE):
        event: response.created
        event: response.in_progress
        event: response.output_text.delta  { delta: "..." }
        event: response.output_text.done   { text: "..." }
        event: response.completed          { response: {...} }
    """
    input_blocks, instructions = _build_responses_input(
        system_instruction, user_text, images,
    )
    payload = {
        "model": MODEL_MULTI_AGENT,
        "input": input_blocks,
        "agent_count": agent_count,  # 4 or 16; 4 is the Grok/Harper/Benjamin/Lucas set
        "stream": True,
    }
    if instructions:
        payload["instructions"] = instructions
    if prompt_cache_key:
        # xAI honors prompt_cache_key on the Responses API — routes this
        # request to the same server that cached a previous identical
        # prefix so we pay cached ($0.20/M) instead of fresh ($2.00/M)
        # for the big training-corpus prefix.
        payload["prompt_cache_key"] = prompt_cache_key

    accumulated = ""
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
        async with client.stream(
            "POST", XAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        ) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise RuntimeError(
                    f"Grok multi-agent HTTP {resp.status_code}: "
                    f"{body.decode('utf-8', errors='replace')[:400]}"
                )
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str:
                    continue
                try:
                    data = json.loads(data_str)
                except Exception:
                    continue
                # We only care about delta events; the other events
                # (response.created, in_progress, completed, etc.) carry
                # bookkeeping we don't need.
                if data.get("type") == "response.output_text.delta":
                    piece = data.get("delta") or ""
                    if piece:
                        accumulated += piece
                        if on_chunk:
                            try:
                                await on_chunk(accumulated)
                            except Exception as cb_err:
                                print(f"[grok-ma] chunk cb error: {cb_err}")
                elif data.get("type") == "response.output_text.done":
                    # Safety net — if we somehow missed deltas, the
                    # "done" event carries the full text.
                    final = data.get("text") or ""
                    if final and not accumulated:
                        accumulated = final
                        if on_chunk:
                            try:
                                await on_chunk(accumulated)
                            except Exception:
                                pass
                elif data.get("type") == "response.completed":
                    # Log cache stats so user can see the full-corpus
                    # prefix is actually being cached. On the first call
                    # cached_tokens will be ~0 (cold); subsequent calls
                    # should show ~600k cached when full training is on.
                    try:
                        resp_obj = data.get("response") or {}
                        usage = resp_obj.get("usage") or {}
                        inp_tok = usage.get("input_tokens", 0)
                        inp_det = usage.get("input_tokens_details") or {}
                        cached = inp_det.get("cached_tokens", 0)
                        out_det = usage.get("output_tokens_details") or {}
                        reasoning_tok = out_det.get("reasoning_tokens", 0)
                        cost_ticks = usage.get("cost_in_usd_ticks", 0)
                        cost_usd = cost_ticks / 1e10 if cost_ticks else 0.0
                        pct = (cached / inp_tok * 100) if inp_tok else 0
                        print(f"[grok-ma] usage: input={inp_tok:,} "
                              f"(cached={cached:,}, {pct:.0f}% hit) "
                              f"reasoning={reasoning_tok:,} "
                              f"cost~${cost_usd:.3f}")
                    except Exception:
                        pass
    return accumulated


# ---------------------------------------------------------------------------
# Streaming (standard chat-completions / reasoning path)
# ---------------------------------------------------------------------------


async def _generate_chat_stream(
    system_instruction: str,
    user_text: str,
    images: list[bytes] | None,
    on_chunk: Callable[[str], Awaitable[None]] | None,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout_s: float,
    api_key: str,
    conv_id: str | None = None,
) -> str:
    """Stream through /v1/chat/completions (OpenAI-compat). Used for the
    ``reasoning`` and ``non-reasoning`` single-agent modes."""
    payload = {
        "model": model,
        "messages": _build_chat_messages(system_instruction, user_text, images),
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if conv_id:
        # x-grok-conv-id routes this request to the same xAI server that
        # cached our last identical prefix, maximizing the cache hit
        # rate. Required for the cache to survive across requests.
        headers["x-grok-conv-id"] = conv_id

    accumulated = ""
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
        async with client.stream(
            "POST", XAI_CHAT_URL,
            headers=headers,
            json=payload,
        ) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise RuntimeError(
                    f"Grok chat HTTP {resp.status_code}: "
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
                if choices:
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        accumulated += piece
                        if on_chunk:
                            try:
                                await on_chunk(accumulated)
                            except Exception as cb_err:
                                print(f"[grok] chunk cb error: {cb_err}")
                # Final chunk (include_usage=true) carries usage stats
                # without choices. Log cache metrics for the same
                # diagnostic the multi-agent path prints.
                usage = data.get("usage")
                if usage and isinstance(usage, dict):
                    try:
                        inp_tok = usage.get("prompt_tokens", 0)
                        details = usage.get("prompt_tokens_details") or {}
                        cached = details.get("cached_tokens", 0)
                        pct = (cached / inp_tok * 100) if inp_tok else 0
                        print(f"[grok] usage: input={inp_tok:,} "
                              f"(cached={cached:,}, {pct:.0f}% hit)")
                    except Exception:
                        pass
    return accumulated


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def generate_grok_stream(
    system_instruction: str,
    user_text: str,
    images: list[bytes] | None = None,
    on_chunk: Callable[[str], Awaitable[None]] | None = None,
    mode: str = "multi-agent",
    agent_count: int = 4,
    temperature: float = 0.95,
    max_tokens: int = 32768,
    timeout_s: float = 180.0,
    api_key: str | None = None,
    cache_key: str | None = None,
) -> str:
    """Stream a Grok generation. Default mode is multi-agent so Lucas
    participates in drafting. Returns accumulated text.

    Raises:
        RuntimeError: missing key or non-200 HTTP.
        asyncio.TimeoutError: if the stream exceeds ``timeout_s``.
    """
    key = (api_key or get_grok_api_key()).strip()
    if not key:
        raise RuntimeError(
            "XAI_API_KEY / GROK_API_KEY not set — add one to .env or toggle Grok off"
        )

    normalized_mode = (mode or "multi-agent").lower()
    if normalized_mode == "multi-agent":
        return await _generate_multi_agent_stream(
            system_instruction=system_instruction,
            user_text=user_text,
            images=images,
            on_chunk=on_chunk,
            agent_count=agent_count,
            timeout_s=timeout_s,
            api_key=key,
            prompt_cache_key=cache_key,
        )
    if normalized_mode == "reasoning":
        return await _generate_chat_stream(
            system_instruction=system_instruction,
            user_text=user_text,
            images=images,
            on_chunk=on_chunk,
            model=MODEL_REASONING,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            api_key=key,
            conv_id=cache_key,
        )
    if normalized_mode == "non-reasoning":
        return await _generate_chat_stream(
            system_instruction=system_instruction,
            user_text=user_text,
            images=images,
            on_chunk=on_chunk,
            model=MODEL_NON_REASONING,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            api_key=key,
            conv_id=cache_key,
        )
    raise ValueError(
        f"Unknown grok mode: {mode!r} (expected multi-agent | reasoning | non-reasoning)"
    )
