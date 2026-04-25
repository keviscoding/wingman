"""Good-reply examples library — learn from what you already sent.

Mirror image of ``case_studies.py``. Instead of analyzing chats the user
flagged as bad outcomes, this module harvests POSITIVE reply examples
from every chat the user has NOT flagged as bad. Every message the user
actually sent is an implicit "good enough to ship" signal. Across
hundreds of chats that's a dense personalized style corpus.

At generation time we embed the current chat's tail, find the top-K
most similar past situations, and inject the replies the user actually
chose into the system instruction as few-shot examples. The model
pattern-matches against the user's own proven style rather than the
Flash-distilled Master Playbook summary.

Why this works without fine-tuning
----------------------------------
- Few-shot examples retrieved contextually beat abstract rule lists
  on creative writing tasks.
- The examples are the user's own chosen replies — the freshest possible
  style reference.
- Bootstrapping requires zero user labor: we just walk the chats folder
  and extract (situation → reply) pairs automatically.
- Grows stronger as the user keeps sending messages: the library can be
  rebuilt any time from the current chats folder state.

Design parallels case_studies.py intentionally — same disk layout, same
retrieval contract, same ``format_*_block`` shape. Makes wiring trivial
and both libraries can coexist in the system prompt.

File layout:
    examples_library/.examples.json   — single file, all pairs +
                                         embeddings. One file keeps
                                         load simple (rebuild is
                                         idempotent by hash).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

STORE_DIR = Path(__file__).parent.parent / "examples_library"
STORE_FILE = STORE_DIR / ".examples.json"
EMBED_MODEL = "models/gemini-embedding-001"

# Tuning knobs — kept conservative for v1 so the library stays manageable.
MAX_PAIRS_PER_CHAT = 8         # don't let one long chat dominate
MIN_REPLY_CHARS = 5            # ignore "ok", "k", emoji-only
MAX_REPLY_CHARS = 500          # cut off paragraph-long replies
SITUATION_WINDOW = 8           # messages of context before the reply
MIN_REPLY_WORDS = 2            # filter out 1-word throwaways


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg_field(m, key: str, default: str = "") -> str:
    """Read key from a Message dataclass or dict (mirrors case_studies)."""
    if hasattr(m, key):
        return getattr(m, key) or default
    if isinstance(m, dict):
        return m.get(key, default) or default
    return default


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _format_situation(messages, end_idx: int, window: int = SITUATION_WINDOW) -> str:
    """Render the context window leading up to messages[end_idx]. The
    message at end_idx itself is NOT included — it's the reply we're
    extracting."""
    start = max(0, end_idx - window)
    lines = []
    for m in messages[start:end_idx]:
        speaker = _msg_field(m, "speaker")
        tag = "ME" if speaker == "me" else "HER"
        text = _msg_field(m, "text").strip()
        if not text:
            continue
        # Strip placeholders like [image] / [voice note] — they add noise
        # to semantic matching without adding signal.
        if text.startswith("[") and text.endswith("]") and len(text) < 20:
            continue
        lines.append(f"{tag}: {text}")
    return "\n".join(lines)


def extract_pairs_from_messages(
    messages,
    contact: str,
    max_pairs: int = MAX_PAIRS_PER_CHAT,
) -> list[dict]:
    """Pull (situation → reply) pairs from one chat. Walks messages,
    finds every 'me' reply that has meaningful context before it, grabs
    the preceding window as the situation. Returns newest-first so the
    top N per chat reflect recent style."""
    pairs: list[dict] = []
    for i, m in enumerate(messages):
        speaker = _msg_field(m, "speaker")
        if speaker != "me":
            continue
        text = _msg_field(m, "text").strip()
        if not text or len(text) < MIN_REPLY_CHARS or len(text) > MAX_REPLY_CHARS:
            continue
        if len(text.split()) < MIN_REPLY_WORDS:
            continue
        # Skip media placeholders as the reply itself
        if text.startswith("[") and text.endswith("]"):
            continue
        # Need at least one 'them' message somewhere in the context window
        start = max(0, i - SITUATION_WINDOW)
        ctx = messages[start:i]
        if not any(_msg_field(p, "speaker") == "them" for p in ctx):
            continue
        situation = _format_situation(messages, i)
        if not situation:
            continue
        pairs.append({
            "contact": contact,
            "situation": situation,
            "reply": text,
            "msg_index": i,
        })
    # Keep the newest N so recent style dominates
    pairs = pairs[-max_pairs:]
    return pairs


def _pairs_hash(pairs: list[dict]) -> str:
    """Stable hash of the (contact, situation, reply) triples so we can
    detect whether the underlying chats changed between rebuilds."""
    h = hashlib.sha256()
    for p in pairs:
        h.update(p.get("contact", "").encode("utf-8"))
        h.update(b"\x00")
        h.update(p.get("situation", "").encode("utf-8"))
        h.update(b"\x00")
        h.update(p.get("reply", "").encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Embedding (batched)
# ---------------------------------------------------------------------------


async def _embed_batch(client, texts: list[str], task_type: str) -> list[list[float]]:
    """Embed a batch of texts in a single API call. Gemini's embed_content
    accepts a list, returns the same number of embeddings."""
    if not texts:
        return []
    try:
        from google.genai import types as gtypes
        resp = await asyncio.to_thread(
            client.models.embed_content,
            model=EMBED_MODEL,
            contents=texts,
            config=gtypes.EmbedContentConfig(task_type=task_type),
        )
        return [list(e.values) for e in (resp.embeddings or [])]
    except Exception as exc:
        print(f"[examples] embed_batch failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


@dataclass
class ExampleEntry:
    contact: str
    situation: str
    reply: str
    embedding: list[float]
    msg_index: int


class ExampleStore:
    """Disk-backed store + in-memory index for the good-examples library."""

    def __init__(self, store_dir: Path = STORE_DIR):
        self._dir = store_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._entries: list[ExampleEntry] = []
        self._hash: str = ""
        self._built_at: float = 0.0
        self._loaded: bool = False
        self._building: bool = False
        self._build_progress: tuple[int, int] = (0, 0)  # (done, total)

    # ---------- IO ----------

    def load(self) -> None:
        self._entries.clear()
        if not STORE_FILE.exists():
            self._loaded = True
            return
        try:
            data = json.loads(STORE_FILE.read_text())
            self._hash = data.get("hash", "")
            self._built_at = data.get("built_at", 0.0)
            for e in data.get("examples", []) or []:
                emb = e.get("embedding") or []
                if not emb:
                    continue
                self._entries.append(ExampleEntry(
                    contact=e.get("contact", ""),
                    situation=e.get("situation", ""),
                    reply=e.get("reply", ""),
                    embedding=emb,
                    msg_index=e.get("msg_index", 0),
                ))
        except Exception as exc:
            print(f"[examples] load failed: {exc}")
        self._loaded = True
        if self._entries:
            print(f"[examples] Loaded {len(self._entries)} examples from disk")

    def _save(self) -> None:
        try:
            STORE_FILE.write_text(json.dumps({
                "version": 1,
                "hash": self._hash,
                "built_at": self._built_at,
                "examples": [
                    {
                        "contact": e.contact,
                        "situation": e.situation,
                        "reply": e.reply,
                        "embedding": e.embedding,
                        "msg_index": e.msg_index,
                    }
                    for e in self._entries
                ],
            }, ensure_ascii=False))
        except Exception as exc:
            print(f"[examples] save failed: {exc}")

    # ---------- Query helpers ----------

    @property
    def count(self) -> int:
        return len(self._entries)

    @property
    def is_empty(self) -> bool:
        return not self._entries

    @property
    def is_building(self) -> bool:
        return self._building

    @property
    def build_progress(self) -> tuple[int, int]:
        return self._build_progress

    @property
    def built_at(self) -> float:
        return self._built_at

    # ---------- Bootstrap from existing chats ----------

    async def bootstrap_from_chats(
        self,
        chat_store,
        case_studies_store=None,
        force: bool = False,
    ) -> int:
        """Walk all chats, pull (situation → reply) pairs from the ones
        NOT flagged as bad outcomes, batch-embed them, persist. Skips
        rebuild if the underlying chat set hasn't changed (hash match).

        Returns the number of examples in the library after build.
        """
        if self._building:
            print("[examples] bootstrap already in progress — skipping")
            return self.count

        self._building = True
        self._build_progress = (0, 0)
        try:
            contacts = chat_store.list_contacts()
            flagged = set()
            if case_studies_store is not None:
                try:
                    flagged = set(case_studies_store.all_flagged_contacts())
                except Exception:
                    flagged = set()

            # 1. Extract all pairs across all chats (skipping flagged)
            raw_pairs: list[dict] = []
            skipped_flagged = 0
            for contact in contacts:
                if contact in flagged:
                    skipped_flagged += 1
                    continue
                try:
                    messages = chat_store.load(contact)
                except Exception:
                    continue
                if not messages:
                    continue
                pairs = extract_pairs_from_messages(messages, contact)
                raw_pairs.extend(pairs)

            if not raw_pairs:
                print(f"[examples] No pairs found. "
                      f"(skipped {skipped_flagged} flagged chats)")
                self._entries = []
                self._hash = ""
                self._built_at = time.time()
                self._save()
                return 0

            # 2. Hash check — skip rebuild if chats unchanged
            new_hash = _pairs_hash(raw_pairs)
            if not force and new_hash == self._hash and self._entries:
                print(f"[examples] Hash unchanged ({len(self._entries)} "
                      f"entries) — skipping rebuild")
                return self.count

            print(f"[examples] Extracting pairs: {len(raw_pairs)} from "
                  f"{len(contacts) - skipped_flagged} chats "
                  f"(skipped {skipped_flagged} flagged)")

            # 3. Embed in batches (Gemini embed_content accepts lists).
            # Batch of 100 is the practical sweet spot — larger causes
            # timeouts, smaller wastes round-trips.
            from wingman.config import make_genai_client
            client = make_genai_client()
            BATCH = 100
            total = len(raw_pairs)
            self._build_progress = (0, total)
            new_entries: list[ExampleEntry] = []

            for start in range(0, total, BATCH):
                chunk = raw_pairs[start:start + BATCH]
                texts = [p["situation"] for p in chunk]
                embeddings = await _embed_batch(client, texts, "RETRIEVAL_DOCUMENT")
                if len(embeddings) != len(chunk):
                    # Rotate key and retry once with smaller batch
                    print(f"[examples] Batch embed mismatch "
                          f"({len(embeddings)}/{len(chunk)}) — retrying")
                    try:
                        from wingman.config import rotate_api_key
                        rotate_api_key()
                        client = make_genai_client()
                    except Exception:
                        pass
                    embeddings = await _embed_batch(client, texts, "RETRIEVAL_DOCUMENT")
                for pair, emb in zip(chunk, embeddings):
                    if not emb:
                        continue
                    new_entries.append(ExampleEntry(
                        contact=pair["contact"],
                        situation=pair["situation"],
                        reply=pair["reply"],
                        embedding=emb,
                        msg_index=pair["msg_index"],
                    ))
                self._build_progress = (min(start + BATCH, total), total)
                print(f"[examples] Embedded {self._build_progress[0]}/"
                      f"{self._build_progress[1]}")

            self._entries = new_entries
            self._hash = new_hash
            self._built_at = time.time()
            self._save()
            print(f"[examples] Bootstrap complete: {len(new_entries)} examples "
                  f"(written to {STORE_FILE.name})")
            return len(new_entries)
        except Exception as exc:
            import traceback
            print(f"[examples] bootstrap failed: {exc}")
            traceback.print_exc()
            return self.count
        finally:
            self._building = False
            self._build_progress = (0, 0)

    # ---------- Retrieval ----------

    def retrieve(
        self,
        query_embedding: list[float],
        top_k: int = 4,
        min_similarity: float = 0.60,
        exclude_contact: str = "",
        dedupe_per_contact: int = 2,
    ) -> list[tuple[float, ExampleEntry]]:
        """Cosine sim over all entries, filter by threshold, cap per
        contact so one chat doesn't dominate. Returns top_k sorted
        descending."""
        if not query_embedding or not self._entries:
            return []
        scored: list[tuple[float, ExampleEntry]] = []
        for entry in self._entries:
            if exclude_contact and entry.contact == exclude_contact:
                continue
            sim = _cosine(query_embedding, entry.embedding)
            if sim >= min_similarity:
                scored.append((sim, entry))
        scored.sort(key=lambda t: t[0], reverse=True)
        # Per-contact dedupe so we don't retrieve 4 examples from the
        # same chat just because it's semantically sticky.
        out: list[tuple[float, ExampleEntry]] = []
        per_contact: dict[str, int] = {}
        for sim, entry in scored:
            c = entry.contact
            if per_contact.get(c, 0) >= dedupe_per_contact:
                continue
            out.append((sim, entry))
            per_contact[c] = per_contact.get(c, 0) + 1
            if len(out) >= top_k:
                break
        return out


# ---------------------------------------------------------------------------
# Query-time helpers
# ---------------------------------------------------------------------------


def _live_query_text(messages, tail: int = SITUATION_WINDOW) -> str:
    """Same shape as the saved situations so the embedding space is
    apples-to-apples."""
    if not messages:
        return ""
    return _format_situation(messages, len(messages), window=tail)


async def _embed_query(text: str) -> list[float] | None:
    if not text.strip():
        return None
    try:
        from wingman.config import make_genai_client
        from google.genai import types as gtypes
        client = make_genai_client()
        resp = await asyncio.to_thread(
            client.models.embed_content,
            model=EMBED_MODEL,
            contents=text,
            config=gtypes.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
        )
        if resp and resp.embeddings:
            return list(resp.embeddings[0].values)
    except Exception as exc:
        print(f"[examples] query embed failed: {exc}")
    return None


def format_examples_block(
    hits: list[tuple[float, ExampleEntry]],
) -> str:
    """Render retrieved (situation, reply) pairs as a prompt-ready
    few-shot block. Emphasizes: match the tone/voice, don't quote."""
    if not hits:
        return ""
    lines = [
        "=" * 60,
        "HIGH-QUALITY REPLY EXAMPLES FROM SIMILAR PAST SITUATIONS",
        "Below are real replies I chose to send in chats that resemble "
        "the current one. Match the tone, length, specificity, and "
        "voice of these replies in your output — they represent my "
        "preferred style. DO NOT quote them verbatim. Internalize the "
        "pattern and adapt to THIS conversation.",
        "=" * 60,
    ]
    for i, (sim, entry) in enumerate(hits, start=1):
        lines.append(f"\n### Example {i} — similarity {sim:.2f}")
        lines.append("Situation I was in:")
        lines.append(entry.situation)
        lines.append("Reply I chose:")
        lines.append(entry.reply)
    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


async def retrieve_examples_for_live_chat(
    store: ExampleStore,
    messages,
    exclude_contact: str = "",
    top_k: int = 4,
    min_similarity: float = 0.60,
) -> tuple[list[tuple[float, ExampleEntry]], str]:
    """Top-level entry point: embed current chat's tail, retrieve
    similar good examples, return hits + formatted block."""
    if store.is_empty or not messages:
        return [], ""
    query = _live_query_text(messages)
    if not query.strip():
        return [], ""
    emb = await _embed_query(query)
    if not emb:
        return [], ""
    hits = store.retrieve(
        query_embedding=emb,
        top_k=top_k,
        min_similarity=min_similarity,
        exclude_contact=exclude_contact,
    )
    block = format_examples_block(hits)
    return hits, block
