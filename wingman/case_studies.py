"""Case Study Library — learn from bad outcomes.

When the user flags a chat as a bad outcome (dead chat caused by our
game — not flakes / busy), Flash performs a rich post-mortem on the
full transcript and writes a dense "case study" to disk. At generation
time, we compute a situational embedding of the live chat and pull the
top-K most similar case studies, injecting them as lessons into the
system instruction.

Key design points
-----------------
- Manual flagging only. No auto-detection (user explicitly asked).
- Post-mortem via Flash, not Pro — fast, cheap, deep enough.
- Embedding via ``gemini-embedding-001`` (same semantic space both ways).
- Tiny JSON index on disk. Cosine similarity is fast enough for
  hundreds of case studies.
- Retrieval at generation time adds ~300ms (one embed call). Skipped
  entirely when the index is empty so zero cost until the user flags.
- Case study build runs in a background task so flagging never blocks
  the UI.

File layout (all under repo root):
    case_studies/<contact_slug>.json    — rich case study + embedding
                                          (index is rebuilt in memory at
                                          startup — no separate .index)

Each case study JSON:
    {
      "contact": "...",
      "flagged_at": 171...,
      "note": "optional user note",
      "case_study": { ... Flash output, see CASE_STUDY_PROMPT ... },
      "embedding": [ ... 3072 floats ... ],
      "built_at": 171...,
      "source_message_count": 42
    }
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

STORE_DIR = Path(__file__).parent.parent / "case_studies"
EMBED_MODEL = "models/gemini-embedding-001"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

CASE_STUDY_PROMPT = (
    "You are a forensic text-game analyst. The user flagged this dating chat "
    "as a BAD OUTCOME — the girl stopped responding or the rapport collapsed "
    "because of HIS game (not because she got busy / flaked for a serious "
    "external reason). Your job is to extract a rich, context-specific case "
    "study a future coach could use to avoid this mistake in similar live "
    "situations.\n\n"
    "Be deep and forensic. Multiple root causes are normal — surface them "
    "all. Focus on HIS choices, not her. Do NOT give generic advice "
    "(\"be confident\", \"match her energy\") — be specific to the dynamic "
    "that actually played out here.\n\n"
    "Return STRICT JSON only (no prose wrapper) with these keys:\n"
    "{\n"
    "  \"situation_fingerprint\": \"One dense paragraph describing the state "
    "  at the moment things went wrong: platform, stage of the chat, her "
    "  personality/investment level, tone, topics being discussed, the "
    "  specific dynamic playing out. Concrete language a retrieval system "
    "  can match on in future chats.\",\n"
    "  \"personality_signals\": \"Short description of HER personality/type "
    "  as signaled by HER messages: reply length, emoji use, initiation "
    "  rate, banter style, how open/guarded/playful/dry she is.\",\n"
    "  \"stage\": \"early_rapport | qualification | banter | escalation | "
    "logistics | post_date | stalled\",\n"
    "  \"investment_trajectory\": \"rising | steady | falling | never_started\",\n"
    "  \"turn_point\": {\n"
    "    \"description\": \"Which exchange killed the vibe and why.\",\n"
    "    \"my_last_moves\": [\"short description of each of my last few moves before it died\"],\n"
    "    \"her_response\": \"How she responded / her last signal.\"\n"
    "  },\n"
    "  \"root_causes\": [\n"
    "    \"Specific concrete reasons. Not surface-level. Examples: 'Escalated "
    "sexually before her investment caught up', 'Fell into interviewing mode "
    "with back-to-back questions after she gave a cold response', 'Over-"
    "explained after a takeaway killed the tension'. 2-5 causes.\"\n"
    "  ],\n"
    "  \"transferable_lesson\": \"One-paragraph coach-to-coach lesson: "
    "'When you see [signal], don't do [move]. Instead do [move]. Because "
    "[reason].' Specific enough to generalize to similar live chats.\",\n"
    "  \"warning_signs\": [\n"
    "    \"Concrete observable signals in a LIVE chat that indicate this "
    "mistake is about to repeat. E.g. 'Her replies shorten to under 5 "
    "words', 'She stops asking questions back', 'She switches from "
    "playful to polite'.\"\n"
    "  ]\n"
    "}\n\n"
    "Conversation to analyze (chronological):\n{transcript}"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip().lower()


def _safe_path(contact: str) -> Path:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    return STORE_DIR / f"{_slug(contact)}.json"


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _msg_field(m, key: str, default: str = "") -> str:
    """Read ``key`` from either a Message dataclass or a dict. The live
    conversation stores Message objects; chat files load as dicts. This
    module is called from both paths so it has to accept both."""
    if hasattr(m, key):
        return getattr(m, key) or default
    if isinstance(m, dict):
        return m.get(key, default) or default
    return default


def _build_transcript_text(messages, max_messages: int = 120) -> str:
    """Stringify messages for the post-mortem prompt. Keeps order and
    speaker labels. Caps at ``max_messages`` from the END (we want the
    recent dynamic, not ancient history)."""
    msgs = messages[-max_messages:] if len(messages) > max_messages else messages
    lines = []
    for m in msgs:
        speaker = _msg_field(m, "speaker")
        tag = "ME" if speaker == "me" else "HER"
        text = _msg_field(m, "text").strip()
        t = _msg_field(m, "time_label") or _msg_field(m, "time")
        prefix = f"[{t}] " if t else ""
        lines.append(f"{prefix}{tag}: {text}")
    return "\n".join(lines)


def _build_live_query_text(messages, tail: int = 12) -> str:
    """What we embed at generation time to match against case studies."""
    recent = messages[-tail:]
    return _build_transcript_text(recent, max_messages=tail)


def _parse_json_block(raw: str) -> dict | None:
    if not raw:
        return None
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Store / Index
# ---------------------------------------------------------------------------


@dataclass
class CaseStudyEntry:
    contact: str
    embedding: list[float]
    case_study: dict
    built_at: float


class CaseStudyStore:
    """Disk-backed store + in-memory index for fast retrieval."""

    def __init__(self, store_dir: Path = STORE_DIR):
        self._dir = store_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, CaseStudyEntry] = {}
        self._loaded = False

    # ---------- Disk IO ----------

    def _path(self, contact: str) -> Path:
        return self._dir / f"{_slug(contact)}.json"

    def load(self):
        """Load all case study JSONs from disk into memory."""
        self._entries.clear()
        if not self._dir.exists():
            self._loaded = True
            return
        for f in sorted(self._dir.glob("*.json")):
            if f.name.startswith("."):
                continue
            try:
                data = json.loads(f.read_text())
                contact = data.get("contact", "")
                emb = data.get("embedding") or []
                cs = data.get("case_study") or {}
                if contact and emb and cs:
                    self._entries[contact] = CaseStudyEntry(
                        contact=contact,
                        embedding=emb,
                        case_study=cs,
                        built_at=data.get("built_at", 0),
                    )
            except Exception as exc:
                print(f"[case_studies] Failed to load {f.name}: {exc}")
        self._loaded = True
        if self._entries:
            print(f"[case_studies] Loaded {len(self._entries)} case studies")

    def save_entry(self, contact: str, data: dict):
        """Persist a full case study record to disk + update in-memory index."""
        path = self._path(contact)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        emb = data.get("embedding") or []
        cs = data.get("case_study") or {}
        if emb and cs:
            self._entries[contact] = CaseStudyEntry(
                contact=contact,
                embedding=emb,
                case_study=cs,
                built_at=data.get("built_at", 0),
            )

    def delete(self, contact: str):
        path = self._path(contact)
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass
        self._entries.pop(contact, None)

    def rename(self, old: str, new: str):
        old_path = self._path(old)
        new_path = self._path(new)
        if old_path.exists():
            try:
                data = json.loads(old_path.read_text())
                data["contact"] = new
                new_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
                old_path.unlink()
            except Exception:
                pass
        if old in self._entries:
            entry = self._entries.pop(old)
            entry.contact = new
            self._entries[new] = entry

    def has(self, contact: str) -> bool:
        return contact in self._entries

    def load_case_study(self, contact: str) -> dict | None:
        path = self._path(contact)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    # ---------- Retrieval ----------

    def is_empty(self) -> bool:
        return not self._entries

    def count(self) -> int:
        return len(self._entries)

    def all_flagged_contacts(self) -> list[str]:
        return list(self._entries.keys())

    def retrieve(self, query_embedding: list[float], top_k: int = 3,
                 min_similarity: float = 0.55,
                 exclude_contact: str = "") -> list[tuple[float, CaseStudyEntry]]:
        """Return top_k (similarity, entry) tuples above the threshold."""
        if not query_embedding or not self._entries:
            return []
        scored: list[tuple[float, CaseStudyEntry]] = []
        for contact, entry in self._entries.items():
            if exclude_contact and contact == exclude_contact:
                continue
            sim = _cosine(query_embedding, entry.embedding)
            if sim >= min_similarity:
                scored.append((sim, entry))
        scored.sort(key=lambda t: t[0], reverse=True)
        return scored[:top_k]


# ---------------------------------------------------------------------------
# Builder — runs Flash post-mortem + embedding
# ---------------------------------------------------------------------------


async def _embed_text(client, text: str, task_type: str) -> list[float] | None:
    """Embed a single text using gemini-embedding-001. Returns None on error."""
    if not text.strip():
        return None
    try:
        from google.genai import types as gtypes
        resp = await asyncio.to_thread(
            client.models.embed_content,
            model=EMBED_MODEL,
            contents=text,
            config=gtypes.EmbedContentConfig(task_type=task_type),
        )
        if resp and resp.embeddings:
            return list(resp.embeddings[0].values)
    except Exception as exc:
        print(f"[case_studies] embed_content failed: {exc}")
    return None


async def build_case_study(contact: str, messages: list[dict],
                           note: str = "") -> dict | None:
    """Run Flash post-mortem + embedding for ``contact``. Returns the
    full record ready to persist, or None on failure."""
    from wingman.config import FLASH_MODEL, make_genai_client
    from google.genai import types as gtypes

    if not messages:
        print(f"[case_studies] No messages for {contact}, skipping")
        return None

    transcript = _build_transcript_text(messages)
    prompt = CASE_STUDY_PROMPT.replace("{transcript}", transcript)

    client = make_genai_client()

    # ── Post-mortem via Flash ──
    raw = ""
    last_err = None
    for attempt in range(3):
        try:
            resp = await asyncio.to_thread(
                client.models.generate_content,
                model=FLASH_MODEL,
                contents=prompt,
                config=gtypes.GenerateContentConfig(
                    temperature=0.4,
                    max_output_tokens=4096,
                ),
            )
            raw = (resp.text or "").strip()
            if raw:
                break
        except Exception as exc:
            last_err = exc
            err_str = str(exc)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                from wingman.config import rotate_api_key
                rotate_api_key()
                client = make_genai_client()
                await asyncio.sleep(1)
                continue
            if "503" in err_str or "UNAVAILABLE" in err_str:
                await asyncio.sleep(2 ** (attempt + 1))
                continue
            print(f"[case_studies] Post-mortem failed for {contact}: {exc}")
            return None

    case_study = _parse_json_block(raw)
    if not case_study:
        print(f"[case_studies] Could not parse case study JSON for {contact} "
              f"(last_err={last_err})")
        return None

    # ── Embedding of the fingerprint+personality+lesson ──
    fp_parts = [
        str(case_study.get("situation_fingerprint", "")),
        str(case_study.get("personality_signals", "")),
        str(case_study.get("transferable_lesson", "")),
    ]
    tp = case_study.get("turn_point") or {}
    if isinstance(tp, dict) and tp.get("description"):
        fp_parts.append(str(tp["description"]))
    signs = case_study.get("warning_signs") or []
    if isinstance(signs, list):
        fp_parts.append(" ".join(str(s) for s in signs))
    fingerprint_text = "\n".join(p for p in fp_parts if p)

    embedding = await _embed_text(client, fingerprint_text, "RETRIEVAL_DOCUMENT")
    if not embedding:
        print(f"[case_studies] Embedding failed for {contact} — saving case "
              f"study without embedding (won't be retrievable until rebuilt)")
        embedding = []

    record = {
        "contact": contact,
        "flagged_at": time.time(),
        "note": note or "",
        "case_study": case_study,
        "embedding": embedding,
        "built_at": time.time(),
        "source_message_count": len(messages),
    }
    return record


# ---------------------------------------------------------------------------
# Retrieval block formatter
# ---------------------------------------------------------------------------


def format_case_studies_block(
    hits: list[tuple[float, CaseStudyEntry]],
) -> str:
    """Render retrieved hits as a prompt-ready block to be appended to the
    system instruction. Returns empty string if no hits."""
    if not hits:
        return ""

    lines = [
        "=" * 60,
        "CASE STUDIES FROM PAST CHATS THAT WENT BADLY",
        "These are lessons from chats that died because of our game. If the "
        "current situation resembles any of them, apply the lesson. Do NOT "
        "quote these back — internalize and adjust.",
        "",
        "IMPORTANT: If one or more of these case studies influenced your "
        "move, BRIEFLY acknowledge it inside the \"advice\" field in this "
        "exact format at the end of your advice: "
        "\"[Lesson applied: <short name of case study contact> — <1-line "
        "how it shaped the move>]\". Only include this tag if a lesson "
        "genuinely shaped your recommendation. Do NOT invent a tag if no "
        "lesson fit.",
        "=" * 60,
    ]

    for i, (sim, entry) in enumerate(hits, start=1):
        cs = entry.case_study
        tp = cs.get("turn_point") or {}
        root_causes = cs.get("root_causes") or []
        warnings = cs.get("warning_signs") or []
        stage = cs.get("stage", "")
        trajectory = cs.get("investment_trajectory", "")

        lines.append(f"\n### Case study {i} (similarity {sim:.2f})"
                     f" — stage: {stage} | trajectory: {trajectory}")
        if cs.get("situation_fingerprint"):
            lines.append(f"Situation: {cs['situation_fingerprint']}")
        if cs.get("personality_signals"):
            lines.append(f"Her personality: {cs['personality_signals']}")
        if isinstance(tp, dict) and tp.get("description"):
            lines.append(f"What killed it: {tp['description']}")
        if root_causes:
            lines.append("Root causes:")
            for rc in root_causes[:5]:
                lines.append(f"  • {rc}")
        if warnings:
            lines.append("Warning signs to watch for in a live chat:")
            for w in warnings[:5]:
                lines.append(f"  • {w}")
        if cs.get("transferable_lesson"):
            lines.append(f"Lesson: {cs['transferable_lesson']}")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


async def retrieve_case_studies_for_live_chat(
    store: CaseStudyStore,
    messages: list[dict],
    exclude_contact: str = "",
    top_k: int = 3,
    min_similarity: float = 0.55,
) -> tuple[list[tuple[float, CaseStudyEntry]], str]:
    """Compute a query embedding for the current chat state and return
    the top-K case studies plus a formatted prompt block.

    Empty inputs short-circuit with no API calls.
    """
    if store.is_empty() or not messages:
        return [], ""

    query_text = _build_live_query_text(messages)
    if not query_text.strip():
        return [], ""

    from wingman.config import make_genai_client
    client = make_genai_client()
    query_emb = await _embed_text(client, query_text, "RETRIEVAL_QUERY")
    if not query_emb:
        return [], ""

    hits = store.retrieve(
        query_embedding=query_emb,
        top_k=top_k,
        min_similarity=min_similarity,
        exclude_contact=exclude_contact,
    )
    block = format_case_studies_block(hits)
    return hits, block
