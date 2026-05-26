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
import os
import re
import time
import uuid
from pathlib import Path

from wingman.transcript import ConversationState, Message
from . import db
from .user_context import UserContext


# ---------------------------------------------------------------------------
# Brand / edge protection
# ---------------------------------------------------------------------------
# Anything the AI emits passes through _sanitize_for_user before it
# leaves the server. The model is told via system prompt to never
# reveal its provenance, but prompts can be coaxed — this is a
# defense-in-depth scrubber that mechanically replaces leaks with
# neutral Muzo branding so the moat (training data, model family,
# internal codenames) never leaves our infra in plain text.
#
# Rules:
#   • internal codenames (PWF and variants) → "Muzo"
#   • underlying model family (Gemini / Google) → neutral language
#   • training methodology terms ("fine-tuned on", "tuned model") → soft
#   • the literal model identifier strings → "Muzo"
#
# Order matters: do the longer multi-word phrases first so the
# single-word replacements don't damage them.
_BRAND_SUBS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Multi-word model references
    (re.compile(r"\b(Google'?s?\s+(?:Gemini|gemini)(?:\s+(?:[\d.]+\s*)?(?:Pro|Flash|Lite|Preview|Advanced))*)\b"), "Muzo"),
    (re.compile(r"\bGemini\s+(?:[\d.]+\s*)?(?:Pro|Flash|Lite|Preview|Advanced)\b", re.IGNORECASE), "Muzo"),
    (re.compile(r"\bgemini-[\w.-]+\b", re.IGNORECASE), "Muzo"),
    (re.compile(r"\bGoogle'?s?\s+(?:large language model|LLM|AI|model)\b", re.IGNORECASE), "Muzo"),
    # Training/methodology terms (soften but don't expose technique)
    (re.compile(r"\b(?:fine[- ]tuned\s+on|fine[- ]tuning|finetuned\s+on)\b", re.IGNORECASE), "trained for"),
    (re.compile(r"\btraining\s+(?:dataset|corpus|data)\b", re.IGNORECASE), "training material"),
    # Internal codenames — PWF is "Playing With Fire", the source-text
    # name we never want to surface in user-facing output.
    (re.compile(r"\bPWF\b"), "Muzo"),
    (re.compile(r"\bPlaying[- ]?With[- ]?Fire\b", re.IGNORECASE), "Muzo"),
    # Bare model name (after the qualified phrases above so we don't
    # double-replace things like "Gemini 3.1 Pro")
    (re.compile(r"\bGemini\b"), "Muzo"),
    # If the model says "as an AI made by Google" / similar
    (re.compile(r"\b(?:made|built|created|developed)\s+by\s+Google\b", re.IGNORECASE), "made by Muzo"),
    (re.compile(r"\bI'?m\s+(?:an?\s+)?(?:Google\s+)?(?:AI|language\s+model|LLM)\b", re.IGNORECASE), "I'm Muzo"),
)


def _sanitize_for_user(text: str | None) -> str:
    """Scrub model/training disclosures from any AI-generated text
    before it leaves the server. Idempotent — safe to run multiple
    times. Whitespace and punctuation are preserved."""
    if not text:
        return text or ""
    out = text
    for pat, sub in _BRAND_SUBS:
        out = pat.sub(sub, out)
    return out


def _sanitize_replies(replies: list[dict] | None) -> list[dict]:
    """Apply _sanitize_for_user to every text-bearing field on each
    reply object. Leaves angles/labels alone — those are never
    sensitive."""
    if not replies:
        return []
    out: list[dict] = []
    for r in replies:
        if not isinstance(r, dict):
            continue
        cleaned = dict(r)
        for k in ("text", "reasoning", "why", "explanation"):
            if isinstance(cleaned.get(k), str):
                cleaned[k] = _sanitize_for_user(cleaned[k])
        out.append(cleaned)
    return out


# ---------------------------------------------------------------------------
# Reply copies — small JSONL append, used for analytics + future training
# ---------------------------------------------------------------------------


# Platform-generated UI strings the OCR sometimes captures as if they
# were chat messages. They contaminate downstream chat-matching (e.g.
# "Start the chat with Jess" appears identically across every Hinge
# match named Jess and tricks the same-name adjudicator into merging
# distinct people). Match case-insensitively + tolerate the trailing
# name variant where applicable.
import re as _ui_re

_UI_BOILERPLATE_PATTERNS: tuple[_ui_re.Pattern[str], ...] = (
    # Hinge openers
    _ui_re.compile(r"^start the chat with\b.*$", _ui_re.IGNORECASE),
    _ui_re.compile(r"^you sent a like\b.*$", _ui_re.IGNORECASE),
    _ui_re.compile(r"^new match\b.*$", _ui_re.IGNORECASE),
    # Tinder / Bumble / generic
    _ui_re.compile(r"^it'?s a match\b.*$", _ui_re.IGNORECASE),
    _ui_re.compile(r"^you matched with\b.*$", _ui_re.IGNORECASE),
    _ui_re.compile(r"^you sent a super ?like\b.*$", _ui_re.IGNORECASE),
    _ui_re.compile(r"^your match expires\b.*$", _ui_re.IGNORECASE),
    _ui_re.compile(r"^boost\s*$", _ui_re.IGNORECASE),
    # Instagram / IG DMs
    _ui_re.compile(r"^you replied to\b.*\bstory\b.*$", _ui_re.IGNORECASE),
    _ui_re.compile(r"^you liked\b.*\bphoto\.?$", _ui_re.IGNORECASE),
    _ui_re.compile(r"^liked a message$", _ui_re.IGNORECASE),
    _ui_re.compile(r"^reacted .* to your message$", _ui_re.IGNORECASE),
    # Read-receipt / status strings
    _ui_re.compile(r"^(read|delivered|sent|seen|active now|online)\s*$", _ui_re.IGNORECASE),
    _ui_re.compile(r"^last seen\b.*$", _ui_re.IGNORECASE),
    # Date / day separators OCR sometimes captures as messages
    _ui_re.compile(r"^(today|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*$", _ui_re.IGNORECASE),
    _ui_re.compile(r"^[A-Z][a-z]{2},\s+[A-Z][a-z]{2,9}\s+\d{1,2}\s*$"),  # "Wed, May 13"
    # Snapchat
    _ui_re.compile(r"^you and .* are friends now$", _ui_re.IGNORECASE),
    _ui_re.compile(r"^streak\b.*$", _ui_re.IGNORECASE),
)


def _is_ui_boilerplate(text: str) -> bool:
    """True if ``text`` looks like a platform-generated UI string
    rather than something a person typed. Used during OCR extraction
    to drop these so they never end up persisted as 'messages' and
    contaminate same-name chat matching downstream."""
    t = (text or "").strip()
    if not t:
        return True
    for pat in _UI_BOILERPLATE_PATTERNS:
        if pat.match(t):
            return True
    return False


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
                    if speaker in ("me", "them") and text and not _is_ui_boilerplate(text):
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


def _merge_locked_context(meta: dict | None, extra_context: str) -> str:
    """If the chat has a locked context pinned (and locked is enabled),
    prepend it to whatever extra_context the caller passed in.

    Locked context is set via PATCH /chats/{id}/context. It persists in
    chat.meta_json so it follows the chat across regenerations and
    follow-up screenshots — the user types "she's the climber from
    Hinge, vegan, allergic to cats" once and Muzo remembers it for
    every future generation in that chat.
    """
    if not meta:
        return (extra_context or "").strip()
    locked = (meta.get("locked_context") or "").strip()
    enabled = bool(meta.get("locked_context_enabled"))
    if not locked or not enabled:
        return (extra_context or "").strip()
    extra = (extra_context or "").strip()
    if not extra:
        return locked
    # Locked context first (background) then session-specific context
    # (foreground) so the immediate ask wins on contradictions.
    return f"{locked}\n\n{extra}"


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
    # Scrub on read too — covers chats persisted before the sanitizer
    # was added. New writes are already pre-scrubbed at the source so
    # this is mostly a no-op going forward.
    return {
        "id": chat_id,
        "contact": chat["contact"],
        "messages": chat["messages"],
        "replies": _sanitize_replies(meta.get("last_replies", [])),
        "read": _sanitize_for_user(meta.get("last_read", "")),
        "advice": _sanitize_for_user(meta.get("last_advice", "")),
        "locked_context": meta.get("locked_context", ""),
        "locked_context_enabled": bool(meta.get("locked_context_enabled")),
    }


def delete_chat_for_user(ctx: UserContext, chat_id: str) -> None:
    db.chat_delete(ctx.user_id, chat_id)


# ---------------------------------------------------------------------------
# Quick-capture pipeline (the killer endpoint)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Chat routing — same-name disambiguation
# ---------------------------------------------------------------------------
# When a screenshot's extracted contact name collides with one or more
# existing chats (e.g. two girls both named "Esther"), we can't blindly
# merge into whichever chat row was created first. We need to figure
# out whether the screenshot is a CONTINUATION of an existing thread
# or a NEW chat for a different person with the same first name.
#
# Decision tree:
#   1. No candidates with the same base name → save under proposed name
#   2. Exactly 1 candidate AND clear text overlap between screenshot
#      and the candidate's recent tail → it's a continuation, no Flash
#      call needed (saves money + latency in the common case)
#   3. Otherwise → call the Flash Lite adjudicator. It reads the
#      candidates' recent messages alongside the screenshot and votes
#      "merge into A/B/C" or "new". This is the same module the
#      desktop hotkey uses, ported over for mobile.
#   4. If the adjudicator says "new", suffix a number to the name
#      ("Esther" → "Esther 2") so both chats coexist cleanly.


_OVERLAP_MIN_TEXT_LEN = 25      # reject "lol"/"yeah"/"😭"-tier matches
_OVERLAP_REQUIRED_MATCHES = 2   # need 2 substantive messages overlapping


def _has_message_overlap(
    new_msgs: list[dict],
    cand_msgs: list[dict],
    *,
    tail_len: int = 8,
) -> bool:
    """Strict exact-text overlap between a screenshot and a candidate
    chat's recent tail.

    Used as a "this is obviously the same conversation" short-circuit
    so we can skip the Flash Lite adjudicator on the easy case.

    Strict on purpose — false positives here = silently merging two
    different people whose chats happened to share a casual filler
    message ("lol", "yeah", "😂"). Constraints:

      • Each candidate-tail message must be ≥ 25 chars to count.
        Generic filler phrases below this threshold get ignored.
      • At least ``_OVERLAP_REQUIRED_MATCHES`` distinct substantive
        messages must overlap. One match is too easy to forge with
        a shared opener like "hey x".
      • Speaker side must match too — a "her: yeah" matching a
        "him: yeah" doesn't count.

    This raises the bar enough that almost all real same-name
    collisions now go through the adjudicator (Flash Lite) where
    they belong.
    """
    if not new_msgs or not cand_msgs:
        return False
    cand_tail_keys = {
        (m.get("speaker"), (m.get("text") or "").strip())
        for m in cand_msgs[-tail_len:]
        if len((m.get("text") or "").strip()) >= _OVERLAP_MIN_TEXT_LEN
    }
    if len(cand_tail_keys) < _OVERLAP_REQUIRED_MATCHES:
        # Candidate's tail is all filler; we can't trust an overlap
        # claim either way — defer to the adjudicator.
        return False

    matched: set[tuple[str | None, str]] = set()
    for m in new_msgs[:8]:
        text = (m.get("text") or "").strip()
        if len(text) < _OVERLAP_MIN_TEXT_LEN:
            continue
        key = (m.get("speaker"), text)
        if key in cand_tail_keys:
            matched.add(key)
            if len(matched) >= _OVERLAP_REQUIRED_MATCHES:
                return True
    return False


def _disambiguate_chat_name(proposed: str, existing_names: list[str]) -> str:
    """Return a contact name that doesn't collide with anything in
    ``existing_names``. If the proposed name is free, return as-is;
    otherwise append a counter ("Esther", "Esther 2", "Esther 3"…).
    """
    proposed = (proposed or "").strip() or "Chat"
    existing_lower = {n.strip().lower() for n in existing_names if n}
    if proposed.lower() not in existing_lower:
        return proposed
    n = 2
    while f"{proposed} {n}".lower() in existing_lower:
        n += 1
    return f"{proposed} {n}"


async def _resolve_chat_for_screenshot(
    user_id: str,
    proposed_name: str,
    new_msgs: list[dict],
) -> str:
    """Pick the right chat for an incoming screenshot.

    Returns the contact_name the caller should save under — either an
    existing one (continuation) or a freshly-disambiguated new name.

    Adjudicator failure is treated as "new" so we never silently merge
    two distinct people. Slightly more chats > silent data loss.
    """
    # Step 1: gather same-base-name candidates.
    candidates = db.chats_with_same_base_name(user_id, proposed_name)
    candidates = [c for c in candidates if c.get("messages")]

    # Always log so we can audit disambiguator behavior in production
    # (lets us tell, from runtime logs, whether the path is even firing
    # for a given screenshot — separate from whether it routed correctly).
    cand_summary = ", ".join(
        f"{c['contact']}({len(c['messages'])}msg)" for c in candidates
    ) or "(none)"
    print(
        f"[saas-pipeline] disambiguate proposed={proposed_name!r} "
        f"candidates=[{cand_summary}]"
    )

    if not candidates:
        return proposed_name

    # Step 2: exactly one candidate AND obvious text continuation
    # (last few stored messages re-appear in the screenshot) → merge.
    if len(candidates) == 1 and _has_message_overlap(new_msgs, candidates[0]["messages"]):
        chosen = candidates[0]["contact"]
        print(f"[saas-pipeline] same-name merge (text-overlap) → {chosen}")
        return chosen

    # Step 3: ask Flash Lite to adjudicate. The screenshot is short
    # (typically 2-8 newly-extracted messages) and stored chats vary
    # wildly in length (some 2 msgs, some 40+). Hard error mode: a
    # 2-msg screenshot getting force-merged into a 40-msg "Jess" chat
    # because Flash thinks the names + casual tone "fit". To guard
    # against that, when ANY candidate is dramatically longer than the
    # screenshot we trim its messages to the most recent few so the
    # adjudicator sees comparable conversational surface area, not a
    # giant vocabulary blob it's tempted to match against.
    #
    # We ALSO strip any UI boilerplate strings ("Start the chat with X",
    # "You replied to their story", etc.) from both the screenshot
    # messages and stored candidate tails before handing them to the
    # adjudicator. Otherwise two unrelated Hinge/Tinder/Snap chats both
    # containing the platform's identical "Start the chat with <name>"
    # banner trick the adjudicator into reporting "exact same message
    # → continuation" — which is exactly the bug we hit in production.
    def _clean(msgs: list[dict]) -> list[dict]:
        return [
            m for m in msgs
            if not _is_ui_boilerplate((m.get("text") or ""))
        ]

    new_msgs_clean = _clean(new_msgs)

    try:
        from wingman.match_adjudicator import adjudicate_match

        cand_pairs: list[tuple[str, list[dict]]] = []
        for c in candidates:
            msgs = _clean(c["messages"])
            # Trim to the last ~12 messages — enough context to capture
            # current rapport / topic without overwhelming the adjudicator
            # with a long history that biases toward "merge".
            trimmed = msgs[-12:] if len(msgs) > 12 else msgs
            cand_pairs.append((c["contact"], trimmed))

        chosen, reason = await adjudicate_match(
            new_msgs_clean, cand_pairs,
            extracted_name=proposed_name,
            extracted_platform="",
        )
    except Exception as exc:
        # If Flash is misbehaving, default to "new chat" so we never
        # silently merge two different people.
        print(f"[saas-pipeline] adjudicator errored ({exc}) — treating as new")
        chosen = ""
        reason = "adjudicator error"

    if chosen:
        print(f"[saas-pipeline] same-name merge (adjudicator) → {chosen}: {reason}")
        return chosen

    # Step 4: adjudicator says "new" — suffix a counter.
    existing_names = [c["contact"] for c in candidates]
    new_name = _disambiguate_chat_name(proposed_name, existing_names)
    print(f"[saas-pipeline] same-name new chat → {new_name}")
    return new_name


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

    # Step 2: same-name disambiguation (env-gated kill switch).
    #
    # When two users share a first name (e.g. two girls both named
    # "Esther"), we'd ideally route each screenshot to the right chat
    # via the Flash Lite adjudicator. In practice the adjudicator has
    # been getting tricked by platform UI noise + tone overlap and
    # producing high-confidence false-positive merges. Until we
    # rebuild that flow with a more reliable signal (e.g. message
    # embeddings or platform-specific cues), the feature is OFF.
    #
    # Set WINGMAN_SAMENAME_DISAMBIG=1 in env to re-enable. With it
    # off, we fall back to the original behaviour: same name = same
    # chat row. This is what mobile shipped with originally and is
    # less surprising than wrong splits / wrong merges.
    if os.getenv("WINGMAN_SAMENAME_DISAMBIG", "").strip() in ("1", "true", "yes"):
        contact_name = await _resolve_chat_for_screenshot(
            ctx.user_id, contact_name, new_msgs,
        )

    # Step 3: persist to per-user chat store (Postgres-backed)
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

    # Merge any locked context the user previously pinned to this chat.
    # Locked context lives in chat meta and persists across screenshots /
    # regenerations so the user doesn't have to re-type "she's the
    # girl from the gym, super into climbing" every time.
    merged_context = _merge_locked_context(existing_meta, extra_context)

    # Step 3: generate replies — route by mode
    conv = ConversationState()
    conv.ingest_parsed_messages(appended)

    if mode == "pro":
        replies, read, advice, model_tag, cost = await _generate_pro_for_user_messages(
            ctx, conv.messages, extra_context=merged_context,
            img_bytes=img_bytes,
        )
    else:
        # Quick mode now also receives the screenshot (when available)
        # so Flash 3.5 can pick up read receipts / timestamps / profile
        # vibe — visual cues OCR alone can't capture.
        replies, read, advice, model_tag, cost = await _generate_for_user_messages(
            ctx, conv.messages, extra_context=merged_context,
            img_bytes=img_bytes,
        )

    # Step 4: scrub any model/training disclosures BEFORE persisting
    # so the cached versions are also clean — protects us if we ever
    # change the sanitizer rules later (the historical reads will
    # already be sanitized at storage time).
    replies = _sanitize_replies(replies)
    read = _sanitize_for_user(read)
    advice = _sanitize_for_user(advice)

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
        "model": "muzo",  # never leak which underlying model handled this call
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
    # Same locked-context merge as quick-capture — see helper.
    merged_context = _merge_locked_context(chat["meta"], extra_context)
    if mode == "pro":
        replies, read, advice, model_tag, cost = await _generate_pro_for_user_messages(
            ctx, conv.messages, extra_context=merged_context,
        )
    else:
        replies, read, advice, model_tag, cost = await _generate_for_user_messages(
            ctx, conv.messages, extra_context=merged_context,
        )
    # Scrub before persisting + returning — see notes in quick_capture.
    replies = _sanitize_replies(replies)
    read = _sanitize_for_user(read)
    advice = _sanitize_for_user(advice)
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
        "model": "muzo",
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
        # 16k is enough for thinking + JSON output for our prompt
        # shape (typical thinking 2-4k, output 1-2k). 32k was the
        # desktop default but doubled our cost without measurable
        # quality gain. Reduces per-Pro-generation cost ~40-50%.
        kwargs = {
            "system_instruction": build_system_instruction(safe),
            "temperature": 0.9,
            "max_output_tokens": 16384,
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
    img_bytes: bytes | None = None,
) -> tuple[list[dict], str, str, str, float]:
    """Quick mode dispatcher.

    Routes to whichever engine ``WINGMAN_QUICK_PATH`` env var selects:
      - "flash35" (DEFAULT) — Gemini 3.5 Flash via AI Studio
      - "tuned"             — fine-tuned Flash V2 on Vertex AI (legacy)

    Falls back to Pro on any failure so users always get something.

    ``img_bytes`` is the original screenshot when available (quick-capture
    flow). When set, the flash35 path attaches it as a multimodal input
    so the model sees read receipts, timestamps, profile photo, online
    status, etc. — visual context the OCR text alone can't capture.
    Regenerate has no image, so it just runs text-only.
    """
    from wingman.config import QUICK_PATH

    if QUICK_PATH == "tuned":
        # Tuned-V2 endpoint is text-only by design; the hedged tuned
        # client doesn't take images. Skip img_bytes here.
        return await _generate_quick_via_tuned(ctx, messages, extra_context)

    # Default path — Flash 3.5 (multimodal)
    try:
        return await _generate_quick_via_flash35(
            ctx, messages, extra_context, img_bytes=img_bytes,
        )
    except Exception as exc:
        print(f"[saas-pipeline] flash35 quick errored ({exc}) — falling back to pro")
        return await _generate_pro_for_user_messages(
            ctx, messages, extra_context=extra_context, img_bytes=img_bytes,
        )


async def _generate_quick_via_flash35(
    ctx: UserContext,
    messages: list[Message],
    extra_context: str = "",
    img_bytes: bytes | None = None,
) -> tuple[list[dict], str, str, str, float]:
    """Fast path using Gemini 3.5 Flash via AI Studio.

    Full feature parity with Pro mode except for the underlying model:
      - REPLY_SYSTEM_PROMPT (personality + identity + brand-edge rules)
      - Master Playbook (~9KB) injected in system_instruction
      - Time context, transcript, extra context, JSON format reminder
      - Multimodal: screenshot attached when available
      - Permissive safety settings
      - 3-tier retry: full+image → full-noimg → safe-prompt-noimg.
        Mirrors Pro's tier strategy so spicy chats that get blocked by
        Gemini's content filter don't bleed through to Pro (which
        would 30x our cost for what could've been a Flash retry).

    Raises only when ALL three tiers fail. The dispatcher then falls
    through to Pro as a last resort.
    """
    from wingman.config import (
        QUICK_MODEL, REPLY_SYSTEM_PROMPT, REPLY_SYSTEM_PROMPT_SAFE,
        make_genai_client, rotate_api_key,
        permissive_safety_settings, _ALL_KEYS,
    )
    from wingman.training_rag import TrainingRAG
    from google.genai import types as gtypes
    from datetime import datetime

    transcript = _format_transcript(messages)

    # Load Master Playbook so 3.5 Flash gets the same personality
    # context Pro does. Cached via TrainingRAG; ~9KB of distilled
    # patterns from 121 training transcripts.
    playbook = ""
    try:
        rag = TrainingRAG()
        rag.load()
        playbook = (rag.knowledge_summary or "").strip()
    except Exception as exc:
        print(f"[saas-pipeline] playbook load failed (quick): {exc}")

    def build_system_instruction(safe: bool) -> str:
        """Strip the trailing 'Conversation: {transcript}' placeholder
        from the prompt template (we put the transcript in the user
        turn instead) and concat the Master Playbook."""
        base = REPLY_SYSTEM_PROMPT_SAFE if safe else REPLY_SYSTEM_PROMPT
        rules_only = base.split("Conversation:\n{transcript}")[0].rstrip()
        parts = [rules_only]
        if playbook:
            parts.append(playbook)
        return "\n\n".join(parts)

    def build_user_prompt() -> str:
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
            print(f"[saas-pipeline] quick image-part build failed: {exc}")

    def build_config(safe: bool):
        # 8k leaves comfortable headroom for JSON output without
        # truncation. Pro uses 16k because 3.1 Pro does extensive
        # internal "thinking" before output; Flash 3.5 doesn't, so
        # 8k is plenty (typical generation only uses 600-800 tokens).
        kwargs = {
            "system_instruction": build_system_instruction(safe),
            "temperature": 0.95,
            "max_output_tokens": 8192,
            "response_mime_type": "application/json",
        }
        try:
            kwargs["safety_settings"] = permissive_safety_settings()
        except Exception:
            pass
        return gtypes.GenerateContentConfig(**kwargs)

    async def attempt(safe: bool, with_image: bool) -> tuple[bool, dict | None, str]:
        """One tier of the retry strategy. Returns (succeeded, parsed, err).

        Rotates Gemini API keys on rate-limit / timeout. Surfaces
        PROHIBITED_CONTENT separately so the caller can choose a
        safer reframing on the next tier.
        """
        prompt = build_user_prompt()
        contents: list = [prompt]
        if with_image and image_part is not None:
            contents.append(image_part)
            contents.append(
                "The screenshot above shows the actual chat. Use it for "
                "visual context — read receipts, timestamps, online "
                "status, profile photo vibe, anything text alone misses."
            )
        client = make_genai_client()
        for _ in range(max(1, len(_ALL_KEYS))):
            try:
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.models.generate_content,
                        model=QUICK_MODEL,
                        contents=contents,
                        config=build_config(safe=safe),
                    ),
                    timeout=30,
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
                if (
                    "PROHIBITED_CONTENT" in err
                    or "blocked" in err.lower()
                    or "safety" in err.lower()
                ):
                    return False, None, "prohibited_content"
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

    # 3-tier retry — same shape as Pro. Best quality first, progressively
    # safer framings on each retry. We only fall through to the
    # dispatcher (= Pro fallback) if ALL three tiers fail.
    tiers: list[tuple[str, bool, bool]] = [
        ("full+image", False, True),    # full prompt + image (best)
        ("full-noimg", False, False),   # drop image (image may have triggered safety)
        ("safe", True, False),          # reframed as analysis
    ]
    errors: list[tuple[str, str]] = []
    data: dict | None = None
    used_tier = ""
    for label, safe, with_image in tiers:
        ok, parsed, err = await attempt(safe=safe, with_image=with_image)
        if ok:
            data = parsed
            used_tier = label
            break
        errors.append((label, err))

    if data is None:
        # Surface in logs the tier-by-tier reasons so we can tell why
        # the Quick path bled through to Pro on this generation.
        print(f"[saas-pipeline] flash35 quick failed across all tiers: {errors}")
        raise RuntimeError(f"flash35 quick exhausted tiers: {errors}")

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
        raise RuntimeError(f"flash35 quick produced 0 valid replies (tier={used_tier})")

    # Cost estimate. 3.5 Flash is roughly $0.10/1M input, $0.40/1M output.
    # Image input adds ~1500 tokens (~$0.00015). Typical generation:
    # ~10k input + ~600 output = ~$0.0013 ≈ 0.13 cents.
    # Bump to 0.30 for the image-attached path.
    cost_cents = 0.30 if image_part is not None else 0.15

    return (
        replies,
        data.get("read", ""),
        data.get("advice", ""),
        QUICK_MODEL,
        cost_cents,
    )


async def _generate_quick_via_tuned(
    ctx: UserContext,
    messages: list[Message],
    extra_context: str = "",
) -> tuple[list[dict], str, str, str, float]:
    """Legacy fast path: tuned Flash V2 on Vertex AI, hedged 5-parallel.

    Returns (replies, read, advice, model_tag, cost_cents).

    Gracefully falls back to Pro when:
      - Vertex AI isn't configured (no service account on this host)
      - Tuned generation returns nothing or errors

    Selected by setting WINGMAN_QUICK_PATH=tuned. Default path is now
    flash35 (see _generate_quick_via_flash35).
    """
    from wingman.tuned_flash_client import (
        generate_tuned_replies_json, is_tuned_configured, get_active_version,
    )

    if not is_tuned_configured():
        print("[saas-pipeline] tuned not configured, falling back to pro")
        return await _generate_pro_for_user_messages(
            ctx, messages, extra_context=extra_context,
        )

    msg_dicts = [
        {"speaker": m.speaker, "text": m.text} for m in messages
    ]
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
    cost_cents = 0.05
    return (
        replies,
        data.get("read", ""),
        data.get("advice", ""),
        f"tuned-{get_active_version()}",
        cost_cents,
    )
