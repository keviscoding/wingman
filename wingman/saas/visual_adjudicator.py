"""Multimodal same-name disambiguator.

The text-only ``wingman.match_adjudicator`` was getting tricked by
shared casual tone + identical platform UI banners (e.g. Hinge's
"Start the chat with Jess" appears verbatim in every Jess match
and looked like decisive continuity evidence to Flash Lite).

This module sends the actual NEW SCREENSHOT plus each candidate's
saved FINGERPRINT IMAGE — the first screenshot of that chat, kept
on disk as a compact JPEG — to a multimodal Gemini call, asking
the model to compare faces / avatars / handles directly.

Two different girls named Jess can write identical openers but
they cannot have the same face. That's why this is the right
disambiguator for dating apps.

Falls back to ``wingman.match_adjudicator.adjudicate_match`` when
none of the candidates have a fingerprint saved yet (legacy chats
from before this feature shipped).
"""

from __future__ import annotations

import asyncio
import json
import string
from typing import Iterable

from wingman.config import (
    FLASH_LITE_MODEL,
    FLASH_MODEL,
    MATCH_ADJUDICATOR_VISUAL_PROMPT,
    QUICK_MODEL,
    make_genai_client,
    rotate_api_key,
)


# Cached flag — once we've confirmed Flash Lite isn't available in the
# current runtime, don't keep retrying on every disambiguation.
_lite_unavailable = False


# A "VisualCandidate" pairs a stored chat's contact name with the
# bytes of its saved fingerprint (None if no fingerprint exists yet)
# and the recent text tail we want the adjudicator to consider.
VisualCandidate = tuple[str, bytes | None, list[dict]]


def _format_msgs(msgs: list[dict], limit: int = 12) -> str:
    """Render a short, human-readable transcript for the prompt."""
    out: list[str] = []
    for m in (msgs or [])[-limit:]:
        speaker = (m.get("speaker") or "?").strip()
        text = (m.get("text") or "").strip().replace("\n", " ")
        if len(text) > 240:
            text = text[:240] + "…"
        out.append(f"{speaker}: {text}")
    return "\n".join(out) if out else "(no recent messages)"


async def _call_visual(
    parts: list,
    model_id: str,
    timeout_s: float = 12.0,
) -> str:
    """Run a single sync multimodal Gemini call off-thread with a
    timeout. Returns the raw response text."""
    from google.genai import types as gtypes

    def _invoke() -> str:
        client = make_genai_client()
        resp = client.models.generate_content(
            model=model_id,
            contents=parts,
            config=gtypes.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=512,
                response_mime_type="application/json",
            ),
        )
        return resp.text or ""

    return await asyncio.wait_for(asyncio.to_thread(_invoke), timeout=timeout_s)


def _build_payload(
    new_screenshot: bytes,
    candidates: list[VisualCandidate],
    extracted_name: str,
) -> tuple[list, dict[str, str], int]:
    """Assemble the multimodal contents list.

    Layout:

      [intro text + screenshot label]
      [NEW SCREENSHOT bytes]

      [CANDIDATE A header text]
      [CANDIDATE A fingerprint bytes — only if available]
      [CANDIDATE A recent message tail text]

      [CANDIDATE B header ...]
      ...

      [final instruction]

    Returns (contents, label_to_contact_map, num_with_image).
    """
    from google.genai import types as gtypes

    letters = string.ascii_uppercase
    label_to_contact: dict[str, str] = {}
    num_with_image = 0
    parts: list = []

    parts.append(
        f"NEW SCREENSHOT (extracted contact name read as \"{extracted_name}\"):"
    )
    parts.append(
        gtypes.Part.from_bytes(data=new_screenshot, mime_type="image/jpeg")
    )

    for idx, (contact, fp_bytes, recent_msgs) in enumerate(candidates):
        letter = letters[idx] if idx < len(letters) else f"Z{idx}"
        label_to_contact[letter] = contact
        parts.append(
            f"\n--- CANDIDATE {letter} (stored as \"{contact}\") ---"
        )
        if fp_bytes:
            parts.append(
                f"CANDIDATE {letter} fingerprint photo (saved from the "
                f"first screenshot of this chat):"
            )
            parts.append(
                gtypes.Part.from_bytes(data=fp_bytes, mime_type="image/jpeg")
            )
            num_with_image += 1
        else:
            parts.append(
                f"CANDIDATE {letter} has NO fingerprint image saved "
                f"(legacy chat). Compare on text only for this candidate."
            )
        parts.append(
            f"CANDIDATE {letter} recent message tail:\n"
            f"{_format_msgs(recent_msgs, limit=12)}"
        )

    parts.append("\n" + MATCH_ADJUDICATOR_VISUAL_PROMPT)
    parts.append("\nYour verdict (strict JSON only):")

    return parts, label_to_contact, num_with_image


async def visual_adjudicate_match(
    new_screenshot: bytes,
    candidates: list[VisualCandidate],
    extracted_name: str = "",
) -> tuple[str, str]:
    """Decide whether ``new_screenshot`` continues any of the
    ``candidates`` chats or is a new person.

    Returns ``(chosen_contact_name, reason)``. ``chosen_contact_name``
    is the empty string for "new" verdicts and for any failure mode
    (so the caller can safely route to a fresh chat).

    Defaults conservatively: medium / low confidence merges are
    treated as "new" — silently merging two different people is a
    worse failure mode than splitting one person across two rows.
    """
    global _lite_unavailable
    if not candidates or not new_screenshot:
        return "", "no candidates or empty screenshot"

    parts, label_to_contact, num_with_image = _build_payload(
        new_screenshot, candidates, extracted_name,
    )

    # Pick a model: 3.5 Flash is cheapest + already vision-capable.
    # Fall back to regular Flash if 3.5 isn't available in this region.
    # Flash Lite is unreliable for image reasoning so we don't use it
    # here even though the text-only adjudicator does.
    model_chain = [QUICK_MODEL, FLASH_MODEL]

    raw_text = ""
    last_err = ""
    for model_id in model_chain:
        try:
            raw_text = await _call_visual(parts, model_id)
            if raw_text.strip():
                break
        except asyncio.TimeoutError:
            last_err = f"{model_id} timed out"
            print(f"[visual-adjudicator] {model_id} timed out — falling back")
            continue
        except Exception as exc:
            last_err = f"{model_id} error: {str(exc)[:200]}"
            msg = str(exc)
            if "404" in msg or "NOT_FOUND" in msg or "not found" in msg.lower():
                continue
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                try:
                    rotate_api_key()
                except Exception:
                    pass
                continue
            print(f"[visual-adjudicator] {model_id} error: {msg[:200]}")
            continue

    if not raw_text:
        return "", f"no response from visual adjudicator ({last_err or 'unknown'})"

    # Light recovery for stray prose around the JSON.
    try:
        data = json.loads(raw_text)
    except Exception:
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
        return "", f"new person ({confidence or 'unrated'}, imgs={num_with_image}): {reason}"

    letter = verdict.strip().upper()[:1]
    if letter not in label_to_contact:
        return "", (
            f"hallucinated verdict {verdict!r} "
            f"(candidates={list(label_to_contact)}): {reason}"
        )

    chosen = label_to_contact[letter]
    # Conservative confidence gate: only "high" confidence merges go
    # through. Anything weaker downgrades to 'new'. The visual path
    # has more signal than text alone — when it's low/medium that
    # means the model itself is unsure, which is exactly when we
    # want to err on the side of a new chat.
    if confidence in ("low", "medium"):
        return "", f"{confidence}-confidence visual ({reason}, imgs={num_with_image}) — treating as new"

    return chosen, f"{confidence or 'unrated'} confidence visual (imgs={num_with_image}): {reason}"


def has_any_fingerprints(candidates: Iterable[VisualCandidate]) -> bool:
    """True if at least one candidate has a saved fingerprint. The
    visual adjudicator can run even when only some candidates have
    fingerprints (the prompt explicitly tells the model to use text
    only for the others), but if ALL of them are missing it's
    cheaper / more accurate to use the text-only adjudicator."""
    return any(fp is not None for _, fp, _ in candidates)
