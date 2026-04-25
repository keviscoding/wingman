"""Lead ranking: auto-analyze all saved chats using PWF frameworks.

Uses Flash to assess each chat's lead status based on text game dynamics.
Processes in batches of 10 to avoid token limit issues on large contact lists.
"""

from __future__ import annotations

import json
import asyncio
from wingman.config import FLASH_MODEL, make_genai_client

BATCH_SIZE = 10


def _build_batch_prompt(chat_blocks: list[str]) -> str:
    return (
        "Rate each chat lead based on text game dynamics. Be BRUTALLY honest.\n\n"
        "SCORING — use the FULL range, do NOT default to middle scores:\n\n"
        "0-1 DEAD: Unmatched, blocked, or completely ghosted.\n"
        "2-3 COLD: One-word replies, left on read, zero investment.\n"
        "4 LUKEWARM: Some replies but low effort, doesn't ask questions.\n"
        "5 NEUTRAL: Back-and-forth exists but no spark.\n"
        "6 INTERESTED: Responding with effort, asking questions, emojis.\n"
        "7 WARM: Clear interest, flirting, IOIs. Close to date.\n"
        "8 HOT: Strong investment, flirting hard, talking logistics.\n"
        "9-10 ON FIRE: Date set, sexting, or actively pursuing meetup.\n\n"
        "PRIORITY: high=text NOW, medium=within 48h, low=dead/wait\n\n"
        "CRITICAL: Use the EXACT contact name as the JSON key — copy it character-for-character "
        "from the '--- Name ---' headers above. Do not modify, shorten, or clean up the names.\n\n"
        "Return JSON:\n"
        "{\"Name\": {\"score\": 0-10, \"tag\": \"cold\"/\"warm\"/\"hot\", "
        "\"reason\": \"1 specific sentence\", \"priority\": \"high\"/\"medium\"/\"low\"}}\n\n"
        + "\n\n".join(chat_blocks)
    )


async def _rank_batch(client, contacts: list[str], chat_blocks: list[str],
                      system: str) -> dict[str, dict]:
    """Rank a single batch of contacts."""
    from google.genai import types
    prompt = _build_batch_prompt(chat_blocks)
    config = types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=8192,
        response_mime_type="application/json",
    )
    if system:
        config.system_instruction = system

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=FLASH_MODEL,
            contents=prompt,
            config=config,
        )
        raw = (response.text or "").strip()
        if not raw:
            print(f"[ranking] Batch returned empty response")
            return {}
        data = json.loads(raw)
        results = {}
        if isinstance(data, dict):
            # Build a lowercase lookup for fuzzy key matching
            lower_map = {c.lower(): c for c in contacts}
            for model_key, val in data.items():
                if not isinstance(val, dict):
                    continue
                # Try exact match, then lowercase match
                matched = None
                if model_key in [c for c in contacts]:
                    matched = model_key
                elif model_key.lower() in lower_map:
                    matched = lower_map[model_key.lower()]
                else:
                    # Partial match — find closest
                    for c in contacts:
                        if model_key.lower() in c.lower() or c.lower() in model_key.lower():
                            matched = c
                            break
                if matched:
                    score = max(0, min(10, int(val.get("score", 5))))
                    tag = "cold" if score <= 3 else "hot" if score >= 7 else "warm"
                    results[matched] = {
                        "score": score,
                        "tag": tag,
                        "reason": val.get("reason", ""),
                        "priority": val.get("priority", "medium"),
                    }
        return results
    except Exception as exc:
        print(f"[ranking] Batch failed: {exc}")
        return {}


async def rank_all_leads(store, contacts: list[str], playbook: str = "") -> dict[str, dict]:
    """Analyze all contacts in batches and return rankings."""
    client = make_genai_client()
    results = {}

    batch_contacts = []
    batch_blocks = []
    for c in contacts:
        msgs = store.load(c)
        if not msgs:
            results[c] = {"score": 0, "tag": "cold", "reason": "No messages yet", "priority": "low"}
            continue
        last_10 = msgs[-10:] if len(msgs) > 10 else msgs
        text = json.dumps(last_10, ensure_ascii=False)
        batch_contacts.append(c)
        batch_blocks.append(f"--- {c} ---\n{text}")

    if not batch_contacts:
        return results

    system = f"You are a dating coach. Use these frameworks:\n\n{playbook}" if playbook else ""

    print(f"[ranking] Analyzing {len(batch_contacts)} contacts in batches of {BATCH_SIZE}...")
    for i in range(0, len(batch_contacts), BATCH_SIZE):
        chunk_contacts = batch_contacts[i:i + BATCH_SIZE]
        chunk_blocks = batch_blocks[i:i + BATCH_SIZE]
        batch_results = await _rank_batch(client, chunk_contacts, chunk_blocks, system)
        results.update(batch_results)
        for c in chunk_contacts:
            if c not in results:
                results[c] = {"score": 5, "tag": "warm", "reason": "Analysis incomplete", "priority": "medium"}
        print(f"[ranking] Batch {i//BATCH_SIZE + 1}: ranked {len(batch_results)}/{len(chunk_contacts)}")

    print(f"[ranking] Done: {len(results)} total contacts ranked")
    return results
