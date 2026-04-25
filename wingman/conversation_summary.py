"""Incremental conversation summarizer.

Summarizes in BLOCKS of BLOCK_SIZE messages. Once a block is summarized,
it's locked in and never re-processed. New blocks are summarized by giving
Flash the PREVIOUS summary + the new block, so context accumulates without
re-reading the entire history.

Example with BLOCK_SIZE=15, KEEP_RECENT=15:
  - 25 msgs: summarize msgs 1-10 (first block), keep 11-25 recent
  - 40 msgs: previous summary + summarize msgs 11-25, keep 26-40 recent
  - 55 msgs: previous summary + summarize msgs 26-40, keep 41-55 recent

Each summary step is ONE cheap Flash call (~200-300 words in, ~200 words out).
Summaries are cached per-contact and only regenerated when a new block fills up.
"""

from __future__ import annotations

import json
from pathlib import Path

from wingman.config import FLASH_MODEL, make_genai_client

KEEP_RECENT = 15
BLOCK_SIZE = 15
SUMMARY_CACHE_DIR = Path(__file__).parent.parent / "chats"

INITIAL_SUMMARY_PROMPT = (
    "Summarize these chat messages into a compact context block (~200-300 words). "
    "This will be the ONLY context an AI coach has about the earlier part of this conversation.\n\n"
    "Cover:\n"
    "- Her personality, texting style, energy level\n"
    "- My approach and how it's landing\n"
    "- Rapport and investment balance\n"
    "- Key moments: flakes, tests, escalation, date plans, inside jokes\n"
    "- Where things stand / trajectory\n"
    "- Red/green flags\n\n"
    "Write in second person ('You opened with...', 'She responded by...'). Be specific.\n\n"
    "Messages:\n{messages}"
)

INCREMENTAL_SUMMARY_PROMPT = (
    "Here is a summary of the EARLIER part of a conversation:\n\n"
    "{previous_summary}\n\n"
    "Now here are the NEXT batch of messages that happened AFTER that summary:\n\n"
    "{new_messages}\n\n"
    "Update the summary to incorporate these new messages. Keep it ~200-300 words. "
    "Maintain everything important from the previous summary, add new developments. "
    "Write in second person. Be specific about what changed."
)


def summarize_if_needed(
    messages: list,
    contact: str,
) -> tuple[str, str]:
    """Returns (summary, recent_messages_json).

    If conversation is short enough, summary is "" and recent is the full transcript.
    If long, summary covers all messages except the last KEEP_RECENT.
    Summary is built incrementally in blocks — only new blocks trigger a Flash call.
    """
    total = len(messages)
    if total <= BLOCK_SIZE + KEEP_RECENT:
        full = json.dumps([m.to_dict() for m in messages], ensure_ascii=False, indent=2)
        return "", full

    # Load existing summary state
    cache = _load_cache(contact)
    cached_count = cache.get("summarized_count", 0)
    cached_summary = cache.get("summary", "")

    # Only summarize in complete blocks of BLOCK_SIZE.
    # summarize_up_to = highest multiple of BLOCK_SIZE that still leaves >= KEEP_RECENT recent msgs
    summarize_up_to = ((total - KEEP_RECENT) // BLOCK_SIZE) * BLOCK_SIZE

    if summarize_up_to <= 0:
        full = json.dumps([m.to_dict() for m in messages], ensure_ascii=False, indent=2)
        return "", full

    # Recent = everything AFTER the last summarized block (grows from 15 up to 30, then resets)
    recent = messages[summarize_up_to:]
    recent_json = json.dumps([m.to_dict() for m in recent], ensure_ascii=False, indent=2)

    if cached_count >= summarize_up_to and cached_summary:
        print(f"[summary] Cached summary covers {cached_count} msgs, feeding {len(recent)} recent")
        return cached_summary, recent_json

    # Build summary incrementally from where we left off
    summary = cached_summary
    cursor = cached_count

    while cursor < summarize_up_to:
        block_end = min(cursor + BLOCK_SIZE, summarize_up_to)
        block = messages[cursor:block_end]
        block_json = json.dumps([m.to_dict() for m in block], ensure_ascii=False, indent=2)

        if not summary:
            print(f"[summary] Initial summary: msgs {cursor+1}-{block_end} for {contact}")
            summary = _generate_initial(block_json)
        else:
            print(f"[summary] Incremental update: msgs {cursor+1}-{block_end} for {contact}")
            summary = _generate_incremental(summary, block_json)

        cursor = block_end

        if not summary:
            print("[summary] Generation failed, using partial")
            break

    if summary:
        _save_cache(contact, cursor, summary)
        print(f"[summary] Summary covers {cursor} msgs, feeding {len(recent)} recent ({len(summary)} chars)")

    return summary, recent_json


def _generate_initial(messages_json: str) -> str:
    try:
        from google.genai import types
        client = make_genai_client()
        response = client.models.generate_content(
            model=FLASH_MODEL,
            contents=INITIAL_SUMMARY_PROMPT.format(messages=messages_json),
            config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=1024),
        )
        return (response.text or "").strip()
    except Exception as exc:
        print(f"[summary] Initial generation failed: {exc}")
        return ""


def _generate_incremental(previous_summary: str, new_messages_json: str) -> str:
    try:
        from google.genai import types
        client = make_genai_client()
        response = client.models.generate_content(
            model=FLASH_MODEL,
            contents=INCREMENTAL_SUMMARY_PROMPT.format(
                previous_summary=previous_summary,
                new_messages=new_messages_json,
            ),
            config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=1024),
        )
        return (response.text or "").strip() or previous_summary
    except Exception as exc:
        print(f"[summary] Incremental generation failed: {exc}")
        return previous_summary


def _cache_path(contact: str) -> Path:
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in contact).strip().lower()
    return SUMMARY_CACHE_DIR / f".summary_{safe}.json"


def _load_cache(contact: str) -> dict:
    path = _cache_path(contact)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save_cache(contact: str, summarized_count: int, summary: str):
    path = _cache_path(contact)
    try:
        path.write_text(json.dumps({
            "summarized_count": summarized_count,
            "summary": summary,
        }))
    except Exception:
        pass
