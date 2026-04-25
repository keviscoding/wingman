"""Glue between the existing reply-generation pipeline and per-user
storage. We deliberately don't fork or rewrite the generation code —
the prompt engineering, tuned-model routing, examples library, case
studies are all our moat. We just point them at user-scoped data
roots via UserContext.

The heavy lifting (Flash extraction, tuned v4 inference, hedged
parallel calls, etc.) is identical to what the desktop personal app
does. The user just doesn't know any of it exists.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

from wingman.chat_store import ChatStore
from wingman.transcript import ConversationState, Message
from .user_context import UserContext


# ---------------------------------------------------------------------------
# Reply copies — small JSONL append, used for analytics + future training
# ---------------------------------------------------------------------------


async def _extract_chat_from_image(img_bytes: bytes) -> tuple[str, list[dict]]:
    """Run RAPID_FIRE_PROMPT against the image with Flash Lite.
    Returns (contact_name, [{speaker, text}, ...]).

    Performance: Flash Lite is ~2-3× faster than Flash and more than
    enough for transcript extraction (which is closer to OCR + light
    structuring than reasoning). max_output_tokens trimmed from 8192 →
    3072 since a typical chat screenshot transcribes to <1500 tokens
    and the model burns thinking-budget against the cap otherwise.
    """
    from wingman.config import (
        FLASH_LITE_MODEL, RAPID_FIRE_PROMPT, make_genai_client, rotate_api_key,
        _ALL_KEYS,
    )
    from google.genai import types as gtypes
    import re as _re

    client = make_genai_client()
    image_part = gtypes.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
    # Build config — disable thinking budget when SDK supports it.
    # Extraction is mechanical (closer to OCR), thinking just adds latency.
    config_kwargs = {
        "temperature": 0.1,
        "max_output_tokens": 3072,
        "response_mime_type": "application/json",
    }
    try:
        config_kwargs["thinking_config"] = gtypes.ThinkingConfig(thinking_budget=0)
    except Exception:
        pass  # Older SDK — thinking is on by default, tolerate it
    config = gtypes.GenerateContentConfig(**config_kwargs)

    last_err = None
    for attempt in range(max(1, len(_ALL_KEYS))):
        try:
            resp = await asyncio.to_thread(
                client.models.generate_content,
                model=FLASH_LITE_MODEL,
                contents=[RAPID_FIRE_PROMPT, image_part],
                config=config,
            )
            raw = (resp.text or "").strip()
            if not raw:
                last_err = "empty"
                continue
            # Strip code fences if any
            fence = _re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
            if fence:
                raw = fence.group(1).strip()
            data = json.loads(raw)
            messages = []
            for m in (data.get("messages") or []):
                speaker = m.get("speaker", "")
                text = (m.get("text") or "").strip()
                if speaker in ("me", "them") and text:
                    messages.append({"speaker": speaker, "text": text})
            return (data.get("contact", "") or "").strip(), messages
        except Exception as exc:
            last_err = str(exc)
            if "429" in last_err or "RESOURCE_EXHAUSTED" in last_err:
                rotate_api_key()
                client = make_genai_client()
                continue
            break
    print(f"[saas-pipeline] extract failed: {last_err}")
    return "", []


def record_reply_copy(ctx: UserContext, chat_id: str, label: str, text: str) -> None:
    log_path = ctx.root / "reply_copies.jsonl"
    rec = {
        "ts": int(time.time()),
        "chat_id": chat_id,
        "label": label,
        "text": text,
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Chat listing / detail / delete
# ---------------------------------------------------------------------------


def _user_chat_store(ctx: UserContext) -> ChatStore:
    """Each user gets a dedicated ChatStore rooted in their data dir.
    The class accepts a ``store_dir`` arg — we just point it there."""
    return ChatStore(store_dir=ctx.chats_dir)


def list_chats_for_user(ctx: UserContext) -> dict:
    store = _user_chat_store(ctx)
    contacts = store.list_contacts()
    out = []
    for c in contacts:
        meta = store.load_meta(c)
        msgs = store.load(c)
        last_text = ""
        last_speaker = ""
        if msgs:
            last_text = (msgs[-1].get("text") or "")[:120]
            last_speaker = msgs[-1].get("speaker", "")
        out.append({
            "id": c,
            "contact": c,
            "msg_count": len(msgs),
            "last_text": last_text,
            "last_speaker": last_speaker,
            "last_activity_at": meta.get("last_activity_at", 0),
            "has_replies": bool(meta.get("last_replies")),
        })
    out.sort(key=lambda d: d["last_activity_at"], reverse=True)
    return {"chats": out}


def get_chat_for_user(ctx: UserContext, chat_id: str) -> dict | None:
    store = _user_chat_store(ctx)
    msgs = store.load(chat_id)
    if not msgs:
        return None
    meta = store.load_meta(chat_id)
    return {
        "id": chat_id,
        "contact": chat_id,
        "messages": msgs,
        "replies": meta.get("last_replies", []),
        "read": meta.get("last_read", ""),
        "advice": meta.get("last_advice", ""),
    }


def delete_chat_for_user(ctx: UserContext, chat_id: str) -> None:
    _user_chat_store(ctx).delete(chat_id)


# ---------------------------------------------------------------------------
# Quick-capture pipeline (the killer endpoint)
# ---------------------------------------------------------------------------


async def quick_capture_for_user(
    ctx: UserContext,
    img_bytes: bytes,
    extra_context: str = "",
    mode: str = "fast",
) -> dict:
    """Extract messages from screenshot → match/create chat → generate
    replies. Returns the unified result dict the route hands to mobile.

    `mode` is "fast" (tuned Flash, default) or "pro" (Gemini 3.1 Pro,
    paid-only with a small free trial). Same extraction stage either
    way — only the reply generation step differs.
    """
    # Step 1: extract contact + messages via Flash Lite — fast,
    # mechanical OCR. Same regardless of generation mode.
    contact_name, new_msgs = await _extract_chat_from_image(img_bytes)
    if not new_msgs:
        return {"replies": []}
    if not contact_name:
        contact_name = f"Chat {int(time.time())}"

    # Step 2: persist to per-user chat store
    store = _user_chat_store(ctx)
    existing = store.load(contact_name) or []
    have = {(m.get("speaker"), m.get("text")) for m in existing}
    appended = list(existing)
    for m in new_msgs:
        key = (m.get("speaker"), m.get("text"))
        if key not in have:
            appended.append(m)
            have.add(key)
    store.save_raw(contact_name, appended)

    # Step 3: generate replies — route by mode
    conv = ConversationState()
    conv.ingest_parsed_messages(appended)

    if mode == "pro":
        replies, read, advice, model_tag, cost = await _generate_pro_for_user_messages(
            ctx, conv.messages, extra_context=extra_context,
        )
    else:
        replies, read, advice, model_tag, cost = await _generate_for_user_messages(
            ctx, conv.messages, extra_context=extra_context,
        )

    # Step 4: persist replies on the chat meta
    meta = store.load_meta(contact_name)
    meta["last_replies"] = replies
    meta["last_read"] = read
    meta["last_advice"] = advice
    meta["last_generated_at"] = time.time()
    store.save_meta(contact_name, meta)

    return {
        "chat_id": contact_name,
        "contact": contact_name,
        "transcript": [
            {"speaker": m.get("speaker"), "text": m.get("text")}
            for m in appended
        ],
        "replies": replies,
        "read": read,
        "advice": advice,
        "model": model_tag,
        "cost_cents": cost,
    }


async def regenerate_for_user(
    ctx: UserContext,
    chat_id: str,
    extra_context: str = "",
    mode: str = "fast",
) -> dict:
    store = _user_chat_store(ctx)
    msgs = store.load(chat_id)
    if not msgs:
        raise KeyError(chat_id)
    conv = ConversationState()
    conv.ingest_parsed_messages(msgs)
    if mode == "pro":
        replies, read, advice, model_tag, cost = await _generate_pro_for_user_messages(
            ctx, conv.messages, extra_context=extra_context,
        )
    else:
        replies, read, advice, model_tag, cost = await _generate_for_user_messages(
            ctx, conv.messages, extra_context=extra_context,
        )
    meta = store.load_meta(chat_id)
    meta["last_replies"] = replies
    meta["last_read"] = read
    meta["last_advice"] = advice
    meta["last_generated_at"] = time.time()
    store.save_meta(chat_id, meta)
    return {
        "chat_id": chat_id,
        "contact": chat_id,
        "replies": replies,
        "read": read,
        "advice": advice,
        "model": model_tag,
        "cost_cents": cost,
    }


# ---------------------------------------------------------------------------
# Internal: route to whichever model SaaS users get
# ---------------------------------------------------------------------------


def _format_transcript(messages: list[Message]) -> str:
    """Render the conversation as the simple JSON shape the desktop
    Pro path uses, so REPLY_SYSTEM_PROMPT.format(transcript=...) gets
    a familiar payload."""
    return json.dumps(
        [{"speaker": m.speaker, "text": m.text} for m in messages],
        ensure_ascii=False,
    )


async def _generate_pro_for_user_messages(
    ctx: UserContext,
    messages: list[Message],
    extra_context: str = "",
) -> tuple[list[dict], str, str, str, float]:
    """High-quality path. Calls Gemini 3.1 Pro with the full reply
    system prompt + Master Playbook injected as system instruction,
    same shape as the desktop personal app's pro path.

    Slower than tuned Flash (~10-15s) but the response quality is
    noticeably stronger on nuanced / longer chats. Paid-only on the
    SaaS frontend with a small free trial gate.
    """
    from wingman.config import (
        PRO_MODEL, REPLY_SYSTEM_PROMPT, make_genai_client, rotate_api_key,
        permissive_safety_settings, _ALL_KEYS,
    )
    from wingman.training_rag import TrainingRAG
    from google.genai import types as gtypes

    transcript = _format_transcript(messages)
    user_prompt = REPLY_SYSTEM_PROMPT.format(transcript=transcript)
    if extra_context.strip():
        user_prompt += f"\n\nExtra context from the user:\n{extra_context.strip()}"

    # System instruction: Master Playbook (the condensed wisdom from
    # 121 training transcripts). Lazily loaded + cached at process
    # level so we pay the cost once.
    system_instr = ""
    try:
        rag = TrainingRAG()
        rag.load()
        system_instr = (rag.knowledge_summary or "").strip()
    except Exception as exc:
        # Degrade gracefully — Pro is still high quality without it.
        print(f"[saas-pipeline] playbook load failed: {exc}")

    client = make_genai_client()
    config_kwargs = {
        "temperature": 0.85,
        "max_output_tokens": 8192,
        "response_mime_type": "application/json",
    }
    if system_instr:
        config_kwargs["system_instruction"] = system_instr
    try:
        config_kwargs["safety_settings"] = permissive_safety_settings()
    except Exception:
        pass
    config = gtypes.GenerateContentConfig(**config_kwargs)

    last_err = None
    for attempt in range(max(1, len(_ALL_KEYS))):
        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    client.models.generate_content,
                    model=PRO_MODEL,
                    contents=user_prompt,
                    config=config,
                ),
                timeout=60,
            )
            raw = (resp.text or "").strip()
            if not raw:
                last_err = "empty"
                continue
            import re as _re
            fence = _re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
            if fence:
                raw = fence.group(1).strip()
            data = json.loads(raw)
            replies = [
                {
                    "label": r.get("label", "option"),
                    "text": r.get("text", ""),
                    "why": r.get("why", ""),
                }
                for r in (data.get("replies") or [])
                if r.get("text")
            ]
            # Pro tokens are pricier — log a fixed-rate estimate.
            cost_cents = 0.5  # ~$0.005 per generation, rough
            return (
                replies,
                data.get("read", ""),
                data.get("advice", ""),
                "pro",
                cost_cents,
            )
        except (asyncio.TimeoutError, Exception) as exc:
            last_err = str(exc)
            if "429" in last_err or "RESOURCE_EXHAUSTED" in last_err or "timeout" in last_err.lower():
                rotate_api_key()
                client = make_genai_client()
                continue
            break

    print(f"[saas-pipeline] pro generation failed: {last_err}")
    return [], "", "", "pro-error", 0.0


async def _generate_for_user_messages(
    ctx: UserContext,
    messages: list[Message],
    extra_context: str = "",
) -> tuple[list[dict], str, str, str, float]:
    """Fast path: tuned v4 Flash, hedged 5-parallel.

    Returns (replies, read, advice, model_tag, cost_cents).

    Gracefully falls back to Pro when:
      - Vertex AI isn't configured (no service account on this host)
      - Tuned generation returns nothing or errors

    The fallback keeps users unblocked — they just get a slower / more
    expensive generation behind the scenes. The mobile app still sees
    a normal "ready" job.
    """
    from wingman.tuned_flash_client import (
        generate_tuned_replies_json, is_tuned_configured, get_active_version,
    )

    if not is_tuned_configured():
        # Vertex not wired on this deploy — fall back so users still
        # get replies. Tag tells us in logs that this isn't ideal.
        print("[saas-pipeline] tuned not configured, falling back to pro")
        return await _generate_pro_for_user_messages(
            ctx, messages, extra_context=extra_context,
        )

    msg_dicts = [
        {"speaker": m.speaker, "text": m.text} for m in messages
    ]
    raw = await generate_tuned_replies_json(
        msg_dicts,
        goal="",
        extra_context=extra_context,
        on_chunk=None,
        timeout_s=20,
    )
    if not raw.strip():
        return [], "", "", f"tuned-{get_active_version()}-empty", 0.0
    try:
        data = json.loads(raw)
    except Exception:
        return [], "", "", f"tuned-{get_active_version()}-badjson", 0.0
    replies = [
        {
            "label": r.get("label", "option"),
            "text": r.get("text", ""),
            "why":  r.get("why", ""),
        }
        for r in (data.get("replies") or [])
        if r.get("text")
    ]
    # Rough cost estimate — 5 calls × ~600 input + 80 output tokens at
    # 2.5 Flash pricing. Not exact; good enough for margin tracking.
    cost_cents = 0.05  # ~$0.0005 per call -> ~$0.0025 per generation
    return (
        replies,
        data.get("read", ""),
        data.get("advice", ""),
        f"tuned-{get_active_version()}",
        cost_cents,
    )
