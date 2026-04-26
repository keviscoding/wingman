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

from wingman.transcript import ConversationState, Message
from . import db
from .user_context import UserContext


# ---------------------------------------------------------------------------
# Reply copies — small JSONL append, used for analytics + future training
# ---------------------------------------------------------------------------


async def _extract_chat_from_image(img_bytes: bytes) -> tuple[str, list[dict]]:
    """Run RAPID_FIRE_PROMPT against the image. Returns (contact_name,
    [{speaker, text}, ...]).

    Robust to model outages: tries Flash Lite (fastest, default), and
    on 503/UNAVAILABLE/quota errors falls back to regular Flash so
    extraction keeps working when Google rate-limits a specific model.
    Both produce comparable output for OCR + light structuring.
    """
    from wingman.config import (
        FLASH_LITE_MODEL, FLASH_MODEL, RAPID_FIRE_PROMPT,
        make_genai_client, rotate_api_key, _ALL_KEYS,
    )
    from google.genai import types as gtypes
    import re as _re

    image_part = gtypes.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
    config_kwargs: dict = {
        "temperature": 0.1,
        "max_output_tokens": 3072,
        "response_mime_type": "application/json",
    }
    try:
        config_kwargs["thinking_config"] = gtypes.ThinkingConfig(thinking_budget=0)
    except Exception:
        pass
    config = gtypes.GenerateContentConfig(**config_kwargs)

    def _is_unavailable(err: str) -> bool:
        u = err.upper()
        return (
            "503" in err
            or "UNAVAILABLE" in u
            or "OVERLOADED" in u
            or "DEADLINE_EXCEEDED" in u
        )

    def _is_quota(err: str) -> bool:
        u = err.upper()
        return "429" in err or "RESOURCE_EXHAUSTED" in u or "RATE LIMIT" in u

    async def _try_model(model_name: str) -> tuple[bool, str, list[dict], str]:
        """Returns (ok, contact, messages, last_err)."""
        client = make_genai_client()
        last_err = ""
        for _ in range(max(1, len(_ALL_KEYS))):
            try:
                resp = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model_name,
                    contents=[RAPID_FIRE_PROMPT, image_part],
                    config=config,
                )
                raw = (resp.text or "").strip()
                if not raw:
                    last_err = "empty"
                    continue
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
                return True, (data.get("contact", "") or "").strip(), messages, ""
            except Exception as exc:
                last_err = str(exc)
                if _is_quota(last_err):
                    rotate_api_key()
                    client = make_genai_client()
                    continue
                # 503 / unavailable → caller will try a different model
                if _is_unavailable(last_err):
                    return False, "", [], last_err
                # Other errors: give up on this model
                return False, "", [], last_err
        return False, "", [], last_err

    # Tier 1: Flash Lite (fast, default)
    ok, contact, messages, err1 = await _try_model(FLASH_LITE_MODEL)
    if ok:
        return contact, messages
    print(f"[saas-pipeline] extract via Flash Lite failed: {err1[:200]}")

    # Tier 2: Flash (regular) — slightly slower but rarely both go down at once
    ok, contact, messages, err2 = await _try_model(FLASH_MODEL)
    if ok:
        print("[saas-pipeline] extract recovered via FLASH_MODEL fallback")
        return contact, messages
    print(f"[saas-pipeline] extract via Flash also failed: {err2[:200]}")

    return "", []


def record_reply_copy(ctx: UserContext, chat_id: str, label: str, text: str) -> None:
    """Stash the last-copied angle on the chat row so the chats list
    can show 'BOLD · last copied' — quick visual recall of which
    tone the user picked last. The fuller copy-event audit log is
    intentionally dropped during the Postgres migration; we'll add
    a copy_events table later when we want it for v5 training data."""
    try:
        chat = db.chat_load(ctx.user_id, chat_id)
        if not chat:
            return
        meta = chat["meta"]
        meta["last_copied_angle"] = label
        meta["last_copied_at"] = int(time.time())
        db.chat_save_meta(ctx.user_id, chat_id, meta)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Chat listing / detail / delete
# ---------------------------------------------------------------------------


def list_chats_for_user(ctx: UserContext) -> dict:
    """Returns every chat the user has stored. Backed by the Postgres
    chats table (was filesystem JSON pre-2026-04-26). Same response
    shape so the mobile client doesn't notice the migration."""
    rows = db.chat_list(ctx.user_id)
    out = []
    for r in rows:
        msgs = r["messages"]
        meta = r["meta"]
        last_text = ""
        last_speaker = ""
        if msgs:
            last_text = (msgs[-1].get("text") or "")[:120]
            last_speaker = msgs[-1].get("speaker", "")
        out.append({
            "id": r["contact"],  # mobile uses the contact name as id
            "contact": r["contact"],
            "msg_count": len(msgs),
            "last_text": last_text,
            "last_speaker": last_speaker,
            "last_activity_at": r["last_activity_at"],
            "has_replies": bool(meta.get("last_replies")),
            "source": meta.get("source"),
            "last_copied_angle": meta.get("last_copied_angle"),
        })
    return {"chats": out}


def get_chat_for_user(ctx: UserContext, chat_id: str) -> dict | None:
    chat = db.chat_load(ctx.user_id, chat_id)
    if not chat or not chat["messages"]:
        return None
    meta = chat["meta"]
    return {
        "id": chat_id,
        "contact": chat["contact"],
        "messages": chat["messages"],
        "replies": meta.get("last_replies", []),
        "read": meta.get("last_read", ""),
        "advice": meta.get("last_advice", ""),
    }


def delete_chat_for_user(ctx: UserContext, chat_id: str) -> None:
    db.chat_delete(ctx.user_id, chat_id)


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

    # Step 2: persist to per-user chat store (Postgres-backed)
    existing = db.chat_load(ctx.user_id, contact_name)
    existing_msgs = existing["messages"] if existing else []
    existing_meta = existing["meta"] if existing else {}
    have = {(m.get("speaker"), m.get("text")) for m in existing_msgs}
    appended = list(existing_msgs)
    for m in new_msgs:
        key = (m.get("speaker"), m.get("text"))
        if key not in have:
            appended.append(m)
            have.add(key)
    db.chat_save(ctx.user_id, contact_name, appended, existing_meta)

    # Step 3: generate replies — route by mode
    conv = ConversationState()
    conv.ingest_parsed_messages(appended)

    if mode == "pro":
        replies, read, advice, model_tag, cost = await _generate_pro_for_user_messages(
            ctx, conv.messages, extra_context=extra_context,
            img_bytes=img_bytes,
        )
    else:
        replies, read, advice, model_tag, cost = await _generate_for_user_messages(
            ctx, conv.messages, extra_context=extra_context,
        )

    # Step 4: persist replies on the chat meta
    existing_meta["last_replies"] = replies
    existing_meta["last_read"] = read
    existing_meta["last_advice"] = advice
    existing_meta["last_generated_at"] = time.time()
    db.chat_save_meta(ctx.user_id, contact_name, existing_meta)

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
    chat = db.chat_load(ctx.user_id, chat_id)
    if not chat or not chat["messages"]:
        raise KeyError(chat_id)
    conv = ConversationState()
    conv.ingest_parsed_messages(chat["messages"])
    if mode == "pro":
        replies, read, advice, model_tag, cost = await _generate_pro_for_user_messages(
            ctx, conv.messages, extra_context=extra_context,
        )
    else:
        replies, read, advice, model_tag, cost = await _generate_for_user_messages(
            ctx, conv.messages, extra_context=extra_context,
        )
    meta = chat["meta"]
    meta["last_replies"] = replies
    meta["last_read"] = read
    meta["last_advice"] = advice
    meta["last_generated_at"] = time.time()
    db.chat_save_meta(ctx.user_id, chat_id, meta)
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
    img_bytes: bytes | None = None,
) -> tuple[list[dict], str, str, str, float]:
    """High-quality path. Calls Gemini 3.1 Pro with the full reply
    system prompt + Master Playbook injected as system instruction.

    Quality features ported from the desktop personal-mode pipeline:
      - **Multimodal**: when the original screenshot bytes are
        available (quick-capture flow), they're attached so Pro sees
        the actual UI — timestamps, profile pics, vibe, etc. The
        transcript-only fallback is used for regenerate (no image).
      - **Safety retry**: if Gemini blocks the first call with
        PROHIBITED_CONTENT (common on explicit chats), retry with
        REPLY_SYSTEM_PROMPT_SAFE — same JSON output, reframed as
        "analyze" rather than "give me replies to send".
      - **Time context**: "now" timestamp injected so the model
        understands recency / how long since the last message.
      - **Permissive safety settings**: BLOCK_NONE for adult content
        categories, since Wingman's domain is explicit dating banter.
    """
    from wingman.config import (
        PRO_MODEL, REPLY_SYSTEM_PROMPT, REPLY_SYSTEM_PROMPT_SAFE,
        make_genai_client, rotate_api_key,
        permissive_safety_settings, _ALL_KEYS,
    )
    from wingman.training_rag import TrainingRAG
    from google.genai import types as gtypes
    from datetime import datetime

    transcript = _format_transcript(messages)

    # Master Playbook — distilled wisdom from 121 training transcripts.
    # Whitelisted in git as training/.master_playbook.json so it ships
    # with every deploy (the raw transcripts stay private).
    playbook = ""
    try:
        rag = TrainingRAG()
        rag.load()
        playbook = (rag.knowledge_summary or "").strip()
    except Exception as exc:
        print(f"[saas-pipeline] playbook load failed: {exc}")
    if not playbook:
        print("[saas-pipeline] WARNING: playbook empty — Pro replies will be vanilla")

    def build_system_instruction(safe: bool) -> str:
        """Match desktop's Pro structure: rules portion of the system
        prompt + Master Playbook in the system_instruction. The
        transcript itself goes in the user prompt below.

        REPLY_SYSTEM_PROMPT contains both rules + a `Conversation:
        {transcript}` placeholder; we strip the placeholder portion
        out so only the rules end up here."""
        base = REPLY_SYSTEM_PROMPT_SAFE if safe else REPLY_SYSTEM_PROMPT
        rules_only = base.split("Conversation:\n{transcript}")[0].rstrip()
        parts = [rules_only]
        if playbook:
            parts.append(playbook)
        return "\n\n".join(parts)

    def build_user_prompt() -> str:
        """Match desktop: time context, transcript, extra context, then
        the explicit JSON format reminder at the end."""
        now = datetime.now().strftime("%A %B %d, %Y at %I:%M %p")
        parts = [
            f"Current date/time: {now}.",
            f"Conversation:\n{transcript}",
        ]
        if extra_context.strip():
            parts.append(f"Additional context: {extra_context.strip()}")
        parts.append(
            "Format as JSON:\n"
            '{"read": "...", "advice": "...", "replies": '
            '[{"label": "...", "text": "...", "why": "..."}]}'
        )
        return "\n\n".join(parts)

    image_part = None
    if img_bytes:
        try:
            image_part = gtypes.Part.from_bytes(
                data=img_bytes, mime_type="image/jpeg",
            )
        except Exception as exc:
            print(f"[saas-pipeline] image-part build failed: {exc}")
            image_part = None

    def build_config(safe: bool):
        # Match desktop's Pro config exactly — temperature 0.9 and a
        # 32k output budget. Pro burns thinking tokens before emitting
        # JSON; an 8k cap was truncating the response and stripping
        # quality. The hard ceiling on Pro is much higher; 32k leaves
        # plenty of room for thinking + the structured JSON output.
        kwargs = {
            "system_instruction": build_system_instruction(safe),
            "temperature": 0.9,
            "max_output_tokens": 32768,
            "response_mime_type": "application/json",
        }
        try:
            kwargs["safety_settings"] = permissive_safety_settings()
        except Exception:
            pass
        return gtypes.GenerateContentConfig(**kwargs)

    async def attempt(safe: bool, with_image: bool) -> tuple[bool, dict | None, str]:
        """Single attempt. Returns (succeeded, parsed_data, last_err).
        Parsed_data is None on failure."""
        prompt = build_user_prompt()
        # contents: text prompt first, then image (if available), then
        # a visual-context note. Mirrors how desktop builds it.
        contents: list = [prompt]
        if with_image and image_part is not None:
            contents.append(image_part)
            contents.append(
                "The screenshot above shows the actual chat. Use it for "
                "visual context (profile photos, read receipts, "
                "timestamps, UI cues)."
            )
        client = make_genai_client()
        for _ in range(max(1, len(_ALL_KEYS))):
            try:
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.models.generate_content,
                        model=PRO_MODEL,
                        contents=contents,
                        config=build_config(safe=safe),
                    ),
                    timeout=50,
                )
                raw = (resp.text or "").strip()
                if not raw:
                    return False, None, "empty"
                import re as _re
                fence = _re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
                if fence:
                    raw = fence.group(1).strip()
                return True, json.loads(raw), ""
            except Exception as exc:
                err = str(exc)
                # Block patterns → caller retries with safer framing
                if (
                    "PROHIBITED_CONTENT" in err
                    or "blocked" in err.lower()
                    or "safety" in err.lower()
                ):
                    return False, None, "prohibited_content"
                # Quota / timeout → rotate key, retry inside this attempt
                if (
                    "429" in err
                    or "RESOURCE_EXHAUSTED" in err
                    or "timeout" in err.lower()
                ):
                    rotate_api_key()
                    client = make_genai_client()
                    continue
                return False, None, err
        return False, None, "all_keys_exhausted"

    # Try in tiers — best quality first, then progressively safer.
    tiers: list[tuple[str, bool, bool]] = [
        ("full+image", False, True),    # full prompt + image (best)
        ("full-noimg", False, False),   # drop image (image may have triggered safety)
        ("safe", True, False),          # reframed as analysis
    ]
    errors: list[tuple[str, str]] = []
    data: dict | None = None
    for label, safe, with_image in tiers:
        ok, parsed, err = await attempt(safe=safe, with_image=with_image)
        if ok:
            data = parsed
            break
        errors.append((label, err))
    if data is None:
        print(f"[saas-pipeline] pro generation failed across all tiers: {errors}")
        return [], "", "", "pro-error", 0.0

    replies = [
        {
            "label": r.get("label", "option"),
            "text": r.get("text", ""),
            "why": r.get("why", ""),
        }
        for r in (data.get("replies") or [])
        if r.get("text")
    ]
    cost_cents = 0.5  # ~$0.005 per generation, rough
    return (
        replies,
        data.get("read", ""),
        data.get("advice", ""),
        "pro",
        cost_cents,
    )


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
    # Tuned can fail at runtime even when configured: Vertex auth bad,
    # endpoint quota, model warm-up timeout. Catch everything and fall
    # back to Pro rather than serving an empty 502 to the user.
    try:
        raw = await generate_tuned_replies_json(
            msg_dicts,
            goal="",
            extra_context=extra_context,
            on_chunk=None,
            timeout_s=20,
        )
    except Exception as exc:
        print(f"[saas-pipeline] tuned errored ({exc}) — falling back to pro")
        return await _generate_pro_for_user_messages(
            ctx, messages, extra_context=extra_context,
        )
    if not raw.strip():
        print("[saas-pipeline] tuned returned empty — falling back to pro")
        return await _generate_pro_for_user_messages(
            ctx, messages, extra_context=extra_context,
        )
    try:
        data = json.loads(raw)
    except Exception:
        print("[saas-pipeline] tuned returned non-JSON — falling back to pro")
        return await _generate_pro_for_user_messages(
            ctx, messages, extra_context=extra_context,
        )
    replies = [
        {
            "label": r.get("label", "option"),
            "text": r.get("text", ""),
            "why":  r.get("why", ""),
        }
        for r in (data.get("replies") or [])
        if r.get("text")
    ]
    if not replies:
        print("[saas-pipeline] tuned produced 0 valid replies — falling back to pro")
        return await _generate_pro_for_user_messages(
            ctx, messages, extra_context=extra_context,
        )
    # Rough cost estimate — 5 calls × ~600 input + 80 output tokens at
    # 2.5 Flash pricing.
    cost_cents = 0.05
    return (
        replies,
        data.get("read", ""),
        data.get("advice", ""),
        f"tuned-{get_active_version()}",
        cost_cents,
    )
