"""Flash-Lite semantic adjudicator for the hotkey chat-matching pipeline.

The local fuzzy matcher in ``server/app.py`` is fast but blind to
semantic reality: it can't reason about conversation flow, banter
style, or whether two chats with the same name are actually the same
person. This module is the escape hatch — a single Flash Lite call
that reads the screenshot's messages alongside up to ~3 candidate
saved chats and says "merge into X" or "new person".

It is called ONLY when the local matcher is uncertain (borderline
score or a same-name collision). Clear-cut continuations are decided
locally and never reach this module.

Safety: any failure (timeout, rate limit, malformed JSON, hallucinated
name) returns ``("", reason)`` so the caller falls back to today's
behaviour. No new failure modes.
"""

from __future__ import annotations

import asyncio
import json
import string
from typing import Iterable

from wingman.config import (
    FLASH_LITE_MODEL,
    FLASH_MODEL,
    MATCH_ADJUDICATOR_PROMPT,
    make_genai_client,
    rotate_api_key,
)

# Cached flag once Lite has been confirmed unavailable for the current
# runtime, so we don't retry it on every capture.
_lite_unavailable = False


def _format_msgs(msgs: list[dict], limit: int = 15) -> str:
    """Render a short, human-readable transcript for the prompt."""
    out = []
    for m in (msgs or [])[-limit:]:
        speaker = (m.get("speaker") or "?").strip()
        text = (m.get("text") or "").strip().replace("\n", " ")
        if len(text) > 240:
            text = text[:240] + "…"
        out.append(f"{speaker}: {text}")
    return "\n".join(out) if out else "(no messages)"


def _build_prompt(
    screenshot_msgs: list[dict],
    candidates: list[tuple[str, list[dict]]],
    extracted_name: str,
    extracted_platform: str,
) -> tuple[str, dict[str, str]]:
    """Return (prompt_text, label_to_contact_map) so we can map the
    adjudicator's 'A'/'B'/'C' verdict back to a real contact name."""
    letters = string.ascii_uppercase
    label_to_contact: dict[str, str] = {}
    candidate_sections = []
    for idx, (name, msgs) in enumerate(candidates):
        letter = letters[idx] if idx < len(letters) else f"Z{idx}"
        label_to_contact[letter] = name
        candidate_sections.append(
            f"--- CANDIDATE {letter} (stored contact: \"{name}\") ---\n"
            f"{_format_msgs(msgs, limit=15)}"
        )

    screenshot_section = (
        f"--- SCREENSHOT (contact name read as: \"{extracted_name}\""
        + (f", platform: {extracted_platform}" if extracted_platform else "")
        + f") ---\n{_format_msgs(screenshot_msgs, limit=15)}"
    )

    prompt = (
        f"{MATCH_ADJUDICATOR_PROMPT}\n\n"
        + "\n\n".join(candidate_sections)
        + f"\n\n{screenshot_section}\n\n"
        "Your verdict (strict JSON only):"
    )
    return prompt, label_to_contact


async def _call_model(prompt: str, model_id: str, timeout_s: float = 10.0) -> str:
    """Run a single synchronous Flash call off-thread with a timeout."""
    from google.genai import types as gtypes

    def _invoke() -> str:
        client = make_genai_client()
        resp = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=gtypes.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=512,
                response_mime_type="application/json",
            ),
        )
        return resp.text or ""

    return await asyncio.wait_for(asyncio.to_thread(_invoke), timeout=timeout_s)


async def adjudicate_match(
    screenshot_msgs: list[dict],
    candidates: list[tuple[str, list[dict]]],
    extracted_name: str = "",
    extracted_platform: str = "",
) -> tuple[str, str]:
    """Ask Flash Lite whether the screenshot matches any candidate.

    Returns ``(chosen_contact_name, reason)``. ``chosen_contact_name``
    is the empty string when:
      • the adjudicator explicitly says "new"
      • the call fails or returns unparseable JSON
      • the answer doesn't match any candidate (hallucination guard)
    """
    global _lite_unavailable
    if not candidates or not screenshot_msgs:
        return "", "no candidates or empty screenshot"

    prompt, label_to_contact = _build_prompt(
        screenshot_msgs, candidates, extracted_name, extracted_platform
    )

    # Try Flash Lite first. If the model ID is wrong or the service
    # is unavailable, silently fall back to regular Flash (once per
    # process, then cached).
    raw_text = ""
    for attempt_model in ([] if _lite_unavailable else [FLASH_LITE_MODEL]) + [FLASH_MODEL]:
        try:
            raw_text = await _call_model(prompt, attempt_model)
            break
        except asyncio.TimeoutError:
            print(f"[adjudicator] {attempt_model} timed out — falling back")
            continue
        except Exception as exc:
            msg = str(exc)
            if "404" in msg or "NOT_FOUND" in msg or "not found" in msg.lower():
                if attempt_model == FLASH_LITE_MODEL and not _lite_unavailable:
                    print(f"[adjudicator] {FLASH_LITE_MODEL} not available — falling back to {FLASH_MODEL}")
                    _lite_unavailable = True
                continue
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                try:
                    rotate_api_key()
                except Exception:
                    pass
                continue
            print(f"[adjudicator] {attempt_model} error: {msg[:200]}")
            continue

    if not raw_text:
        return "", "no response from adjudicator"

    try:
        data = json.loads(raw_text)
    except Exception:
        # Flash sometimes emits code fences or extra text; try to
        # salvage by locating the first JSON object.
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw_text[start : end + 1])
            except Exception:
                return "", f"unparseable JSON: {raw_text[:120]!r}"
        else:
            return "", f"no JSON in response: {raw_text[:120]!r}"

    verdict = str(data.get("verdict", "")).strip()
    confidence = str(data.get("confidence", "")).strip().lower()
    reason = str(data.get("reason", "")).strip()

    if verdict.lower() == "new":
        return "", f"new person ({confidence or 'unrated'}): {reason}"

    # Normalize to single uppercase letter so case/whitespace drift is fine.
    letter = verdict.strip().upper()[:1]
    if letter in label_to_contact:
        chosen = label_to_contact[letter]
        # Low-confidence merges are risky (e.g. Flash is 50/50 on whether
        # two Sienna are the same); refuse rather than guess wrong.
        if confidence == "low":
            return "", f"low-confidence ({reason}) — treating as new"
        return chosen, f"{confidence or 'unrated'} confidence: {reason}"

    return "", f"hallucinated verdict {verdict!r} (candidates={list(label_to_contact)}): {reason}"
