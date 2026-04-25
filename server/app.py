"""FastAPI server — polls Wingman state and pushes to browser."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware

from wingman.main import Wingman, HEADLESS
from wingman.config import SERVER_HOST, SERVER_PORT, REPLY_SYSTEM_PROMPT

STATIC_DIR = Path(__file__).parent / "static"

wingman: Wingman | None = None
ws_clients: set[WebSocket] = set()


async def broadcast(msg: dict):
    payload = json.dumps(msg)
    dead = set()
    for ws in ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    if dead:
        ws_clients.difference_update(dead)


import re as _re
import unicodedata as _ud

# Strip unicode emoji / pictographs / symbols — equal across platforms
# regardless of Flash returning 😉 while storage has ;) or vice versa.
_EMOJI_RE = _re.compile(
    "["
    "\U0001F000-\U0001FFFF"  # supplementary planes
    "\U00002600-\U000027BF"  # misc symbols + dingbats
    "\U0000FE0F"             # variation selector 16
    "\U0000200D"             # zero-width joiner
    "]+",
    flags=_re.UNICODE,
)
# Strip trailing/leading punctuation that commonly drifts across captures
# ("hey.." vs "hey", "Okay!" vs "Okay", etc.). We keep interior chars so
# "you're" stays distinguishable from "you".
_PUNCT_RE = _re.compile(r"[^\w\s']", flags=_re.UNICODE)


def _norm_text(t: str) -> str:
    """Normalize a message for comparison only (never for storage):
      • NFKC-fold (fullwidth → regular, compatibility forms, etc.)
      • lower-case
      • strip emoji/symbol variants
      • strip punctuation other than word chars / whitespace / apostrophes
      • collapse whitespace

    So "Good girl. Save it as Kevis ;)" and "Good girl, Save it as Kevis 😉"
    both fold to "good girl save it as kevis" and fuzzy-match 100.
    """
    if not t:
        return ""
    t = _ud.normalize("NFKC", t).lower()
    t = _EMOJI_RE.sub(" ", t)
    t = _PUNCT_RE.sub(" ", t)
    return " ".join(t.split())


def _msg_texts(messages: list[dict], tail: int) -> list[str]:
    """Last ``tail`` normalized message texts, dropping empties and media
    placeholders like '[image]'. Order preserved (oldest → newest)."""
    out: list[str] = []
    for m in (messages or [])[-tail:]:
        raw = (m.get("text") or "").strip()
        # Detect media placeholders BEFORE normalization, since _PUNCT_RE
        # would strip the brackets.
        if raw.startswith("[") and raw.endswith("]"):
            continue
        t = _norm_text(raw)
        if not t:
            continue
        out.append(t)
    return out


# Tunables. Kept as constants so we can tweak without hunting.
_MATCH_THRESHOLD = 50      # absolute score needed to merge (0-100)
_MATCH_MARGIN = 8          # best must beat second-best by this much
_SCREENSHOT_TAIL = 10      # how many recent screenshot messages to look at
_SAVED_TAIL = 30           # how many recent saved messages to look at
_ALIGN_MSG_RATIO = 80      # per-message fuzzy threshold for alignment
# Distinctiveness thresholds (total chars in the aligned run).
# Short runs from generic openers ("Hey"/"hey x") = ~10 chars; they
# must NOT earn trust by themselves. Real chat content is much longer.
_CHARS_DISTINCTIVE = 60    # strong enough to count even mid-saved
_CHARS_MODERATE = 30       # weaker but still counts


def _alignment_run(
    screenshot: list[str], saved: list[str], fz
) -> tuple[int, bool, int]:
    """Longest contiguous run of fuzzy-matching consecutive messages.
    Tries up to the first 2 screenshot positions as starting anchors,
    to tolerate Flash occasionally adding a stray message at the top.

    Returns ``(run_length, ends_at_saved_tail, total_aligned_chars)``.
    The char count is used by the scorer to distinguish distinctive
    content runs from generic openers — a run of 3 long messages counts
    very differently than a run of 3 "hey"s.
    """
    if not screenshot or not saved:
        return 0, False, 0
    saved_len = len(saved)
    screen_len = len(screenshot)

    best_run = 0
    best_ends_at_tail = False
    best_chars = 0

    # Try a couple of possible screenshot-start anchors. Flash sometimes
    # hallucinates a header/title as "message 0"; starting at index 1
    # lets us still align the rest. 2 anchors is plenty in practice.
    max_start = min(2, screen_len)
    for start_i in range(max_start):
        s_anchor = screenshot[start_i]
        for j in range(saved_len):
            if fz.ratio(s_anchor, saved[j]) < _ALIGN_MSG_RATIO:
                continue
            run = 1
            chars = len(screenshot[start_i])
            while (start_i + run) < screen_len and (j + run) < saved_len:
                if fz.ratio(screenshot[start_i + run], saved[j + run]) < _ALIGN_MSG_RATIO:
                    break
                chars += len(screenshot[start_i + run])
                run += 1
            ends_at_tail = (j + run) == saved_len
            if run > best_run or (run == best_run and ends_at_tail and not best_ends_at_tail):
                best_run = run
                best_ends_at_tail = ends_at_tail
                best_chars = chars
                # Extremely strong signal — stop early.
                if best_run >= 5 and best_ends_at_tail:
                    return best_run, best_ends_at_tail, best_chars

    return best_run, best_ends_at_tail, best_chars


def _score_contact(screenshot_texts: list[str], saved_texts: list[str], fz) -> int:
    """Composite similarity 0-100 between a screenshot and one saved chat.

    Signals, ordered by how decisive they are:
      1. Alignment run (0-55) — consecutive messages in order. Scored
         primarily by TOTAL CHARACTERS of the aligned messages, not just
         the message count, so a short run of generic openers ('hey' +
         'hey x', ~10 chars) stays untrusted while a short run of real
         content ('i have two tattoos' + 'wbu', ~25 chars) earns credit.
         Tail-anchored alignments get extra weight because they represent
         a clean continuation of the stored chat.
      2. Tail partial_ratio (0-30) — overall fuzzy content overlap.
         Dampened only when alignment was short AND not distinctive
         (prevents a tiny, generic-opener screenshot from free-riding on
         substring similarity to a big saved chat).
      3. Last-message match (0-20) — screenshot end vs saved end.
      4. Verbatim count (0-15, capped).
    """
    if not screenshot_texts or not saved_texts:
        return 0

    screen_len = len(screenshot_texts)
    saved_len = len(saved_texts)

    # 1. Contiguous alignment.
    k, ends_at_tail, chars = _alignment_run(screenshot_texts, saved_texts, fz)

    if k == 0:
        align_bonus = 0
    elif ends_at_tail:
        # Continuation of the stored chat — very strong.
        if chars >= _CHARS_DISTINCTIVE or k >= 3:
            align_bonus = 55
        elif chars >= _CHARS_MODERATE or k >= 2:
            align_bonus = 40
        else:
            align_bonus = 18  # k=1 tail anchor only
    else:
        # Alignment sits somewhere inside saved. Trust it proportional
        # to how distinctive the matched content is, not just its
        # message count. This prevents 'Hey trouble'+'hey x' (≈16 chars)
        # from free-merging across girls with the same opener, while
        # still letting any real content overlap (≥60 chars) merge.
        if chars >= _CHARS_DISTINCTIVE:
            align_bonus = 55 if k >= 3 else 45
        elif chars >= _CHARS_MODERATE and k >= 2:
            align_bonus = 32
        else:
            align_bonus = 0

    # 2. Tail partial_ratio.
    sig_s = " | ".join(screenshot_texts)
    sig_v = " | ".join(saved_texts)
    partial = fz.partial_ratio(sig_s, sig_v)
    coverage = screen_len / max(saved_len, 1)
    # Only dampen when BOTH alignment was short+generic AND screenshot
    # is a tiny sliver of saved. Distinctive alignments keep full score.
    if (not ends_at_tail
            and chars < _CHARS_MODERATE
            and coverage < 0.5):
        partial *= 0.3
    partial_score = partial * 0.3  # 0-30 range

    # 3. Last message bonus.
    last_s = screenshot_texts[-1]
    last_v = saved_texts[-1]
    if last_s == last_v:
        last_bonus = 20
    else:
        r = fz.ratio(last_s, last_v)
        last_bonus = max(0, (r - 70) * 0.4)  # 0 at r=70, 12 at r=100

    # 4. Verbatim count.
    saved_set = set(saved_texts)
    verbatim = sum(1 for t in screenshot_texts if t in saved_set)
    verbatim_score = min(verbatim * 3, 15)

    return min(100, int(align_bonus + partial_score + last_bonus + verbatim_score))


def _match_by_transcript_overlap(
    extracted_messages: list[dict], saved: list[str], store
) -> tuple[str, int]:
    """The ONLY merge signal: composite similarity between the screenshot
    and every saved chat. Returns (contact, score) if the best chat beats
    both ``_MATCH_THRESHOLD`` and the runner-up by ``_MATCH_MARGIN``.

    The margin rule protects against picking the wrong Amy when two
    similar chats both look vaguely right — we prefer to create a fresh
    disambiguated chat instead of silently merging into the wrong one.
    """
    screenshot_texts = _msg_texts(extracted_messages, _SCREENSHOT_TAIL)
    if len(screenshot_texts) < 2 or not saved:
        return "", 0
    try:
        from thefuzz import fuzz as _fz
    except Exception:
        return "", 0

    best_contact = ""
    best_score = 0
    second_score = 0

    for contact in saved:
        try:
            stored = store.load(contact)
        except Exception:
            continue
        if not stored:
            continue
        saved_texts = _msg_texts(stored, _SAVED_TAIL)
        if not saved_texts:
            continue

        s = _score_contact(screenshot_texts, saved_texts, _fz)

        if s > best_score:
            second_score = best_score
            best_score = s
            best_contact = contact
            if best_score >= 95:
                break
        elif s > second_score:
            second_score = s

    if best_score < _MATCH_THRESHOLD:
        return "", best_score
    # Ambiguity guard — if the runner-up is close, refuse to merge.
    if (best_score - second_score) < _MATCH_MARGIN:
        return "", best_score
    return best_contact, best_score


def _is_strong_local_match(
    screenshot_texts: list[str],
    saved_texts: list[str],
    fz,
    score: int,
) -> bool:
    """A 'strong' local match is one where we're confident enough to
    skip the Flash-Lite adjudicator and merge immediately. Criteria:
      • composite score ≥ 70
      • alignment k ≥ 3
      • alignment is tail-anchored (true continuation)
      • aligned content ≥ _CHARS_DISTINCTIVE (not just generic openers)
    All four must hold. This keeps the fast path for genuinely
    unambiguous cases while routing everything else to Flash.
    """
    if score < 70:
        return False
    k, ends_at_tail, chars = _alignment_run(screenshot_texts, saved_texts, fz)
    return k >= 3 and ends_at_tail and chars >= _CHARS_DISTINCTIVE


def _base_name_lower(name: str) -> str:
    """Strip a trailing ' (N)' disambiguator so we can group same-person chats.
    'Amy' -> 'amy' ; 'Amy (2)' -> 'amy' ; 'whatsapp - Cyn (4)' -> 'whatsapp - cyn'."""
    import re as _re
    return _re.sub(r"\s*\(\d+\)\s*$", "", (name or "").strip()).strip().lower()


def _name_collides(proposed: str, saved: list[str]) -> bool:
    """Does any saved chat share the same base name (case-insensitive,
    ignoring '(N)' suffix) as the proposed name?"""
    if not proposed or not saved:
        return False
    base = _base_name_lower(proposed)
    if not base:
        return False
    return any(_base_name_lower(s) == base for s in saved)


def _gather_candidates(
    proposed: str,
    local_best: str,
    local_best_score: int,
    saved: list[str],
    store,
    max_candidates: int = 3,
) -> list[tuple[str, list[dict]]]:
    """Collect up to ~3 chats worth feeding to Flash Lite:
      • every saved chat whose base name matches `proposed` (Katy, Katy (2))
      • plus the local matcher's top result if it scored ≥ 30 and isn't
        already in the name group.
    Each candidate ships with its last 30 messages. Empty chats are
    excluded (nothing useful to compare)."""
    base = _base_name_lower(proposed)
    collected: list[tuple[str, list[dict]]] = []
    seen: set[str] = set()

    for contact in saved:
        if _base_name_lower(contact) != base:
            continue
        if contact in seen:
            continue
        try:
            msgs = store.load(contact) or []
        except Exception:
            continue
        if not msgs:
            continue
        collected.append((contact, msgs[-30:]))
        seen.add(contact)
        if len(collected) >= max_candidates:
            break

    # Add the local matcher's best if it's a different contact and scored
    # at least some overlap — it might be the same person under a renamed key.
    if (
        local_best
        and local_best not in seen
        and local_best_score >= 30
        and len(collected) < max_candidates
    ):
        try:
            msgs = store.load(local_best) or []
            if msgs:
                collected.append((local_best, msgs[-30:]))
                seen.add(local_best)
        except Exception:
            pass

    return collected


def _disambiguate_name(proposed: str, saved: list[str], store=None) -> str:
    """Return a contact name for a newly-detected chat.

    Preference order:
      1. If the bare ``proposed`` name doesn't exist yet → use it.
      2. If it exists but the on-disk chat is EMPTY (a leftover placeholder
         from a previous failed capture) → reuse that name. This prevents
         the 'parade of empty ghost chats' problem where each failed
         capture spawns another ``Cyn (N+1)``.
      3. Otherwise try ``"proposed (2)"``, ``"proposed (3)"``… and reuse
         any that happen to be empty. Finally, pick the first unused.

    Non-empty chats with the same name are NEVER reused — that would
    silently merge two different people.
    """
    if not proposed:
        return proposed
    saved_lower = {s.lower(): s for s in (saved or [])}

    def _is_empty(real_name: str) -> bool:
        if not store:
            return False
        try:
            return not store.load(real_name)
        except Exception:
            return False

    # Try the bare name, then (2), (3), ...
    for n in range(1, 200):
        cand = proposed if n == 1 else f"{proposed} ({n})"
        cand_lower = cand.lower()
        if cand_lower not in saved_lower:
            return cand  # brand-new name slot
        existing = saved_lower[cand_lower]
        if _is_empty(existing):
            return existing  # reuse stale empty placeholder
    return f"{proposed} ({len(saved) + 1})"  # worst case, never hit in practice


def _contact_previews(w) -> dict:
    """Return last message preview + metadata for each contact (for sidebar)."""
    previews = {}
    for c in w.saved_contacts:
        msgs = w.store.load(c)
        meta = w.store.load_meta(c)
        preview = ""
        if msgs:
            last = msgs[-1]
            text = last.get("text", "")
            speaker = last.get("speaker", "")
            prefix = "You: " if speaker == "me" else ""
            preview = prefix + (text[:40] + "..." if len(text) > 40 else text)
        recep = meta.get("receptiveness", 5)
        has_replies = bool(meta.get("last_replies"))
        lead_tag = meta.get("lead_tag", "")
        lead_reason = meta.get("lead_reason", "")
        lead_priority = meta.get("lead_priority", "")
        last_gen = meta.get("last_generated_at", 0)
        last_act = meta.get("last_activity_at", 0)
        # Bad-outcome flag: meta stores {flagged_at, note, built_at?}.
        # ``analyzing`` means the flag exists but the Flash post-mortem
        # hasn't finished writing yet (either still running or it failed).
        bad = meta.get("bad_outcome") or {}
        bad_outcome_flagged = bool(bad)
        case_study_ready = w.case_studies.has(c) if bad_outcome_flagged else False
        case_study_analyzing = (
            bad_outcome_flagged
            and (c in getattr(w, "_building_case_studies", set()))
        )
        previews[c] = {
            "preview": preview, "receptiveness": recep, "has_replies": has_replies,
            "lead_tag": lead_tag, "lead_reason": lead_reason, "lead_priority": lead_priority,
            "last_generated_at": last_gen,
            "last_activity_at": last_act,
            "bad_outcome": bad_outcome_flagged,
            "case_study_ready": case_study_ready,
            "case_study_analyzing": case_study_analyzing,
            "bad_outcome_note": (bad.get("note") or "") if isinstance(bad, dict) else "",
        }
    return previews


def _state() -> dict:
    w = wingman
    # Refresh from disk every state build so the UI never shows stale
    # lists when in-memory state drifts (e.g. external writes, missed
    # refresh in a write path, import/replace operations). Both calls
    # are cheap disk reads.
    try:
        w.saved_contacts = w.store.list_contacts()
    except Exception:
        pass
    try:
        w.presets.refresh()
    except Exception:
        pass
    try:
        w.global_settings.refresh()
    except Exception:
        pass
    return {
        "status": w.status,
        "messages": len(w.conversation.messages),
        "has_replies": len(w.latest_replies) > 0,
        "contact": w.current_contact,
        "contacts": w.saved_contacts,
        "contact_previews": _contact_previews(w),
        "headless": w.headless,
        "mic_muted": getattr(w.live, "mic_muted", False),
        "collecting_count": w.collecting_count,
        "training_status": w.training_rag.status,
        "training_files": w.training_rag.file_count,
        "training_tokens": 0,
        "presets": w.presets.presets,
        "active_preset": w.active_preset,
        "default_preset": w.default_preset,
        "replies_version": w.replies_version,
        "server_session_id": w.server_session_id,
        "reply_model": w.reply_model,
        "use_training": w.use_training,
        "use_kie": getattr(w, "use_kie", False),
        "kie_configured": (__import__("wingman.kie_client", fromlist=["is_kie_configured"]).is_kie_configured()),
        "tuned_configured": (__import__("wingman.tuned_flash_client", fromlist=["is_tuned_configured"]).is_tuned_configured()),
        "tuned_version": (__import__("wingman.tuned_flash_client", fromlist=["get_active_version"]).get_active_version()),
        "tuned_versions_available": (__import__("wingman.tuned_flash_client", fromlist=["get_available_versions"]).get_available_versions()),
        "use_grok": getattr(w, "use_grok", False),
        "grok_mode": getattr(w, "grok_mode", "multi-agent"),
        "grok_full_training": getattr(w, "grok_full_training", True),
        "grok_corpus_files": w.training_corpus.file_count,
        "grok_corpus_chars": w.training_corpus.char_count,
        "grok_configured": (__import__("wingman.grok_client", fromlist=["is_grok_configured"]).is_grok_configured()),
        "use_deepseek": getattr(w, "use_deepseek", False),
        "deepseek_mode": getattr(w, "deepseek_mode", "normal"),
        "deepseek_variant": getattr(w, "deepseek_variant", "pro"),
        "deepseek_configured": (__import__("wingman.deepseek_client", fromlist=["is_deepseek_configured"]).is_deepseek_configured()),
        "use_lessons": getattr(w, "use_lessons", True),
        "case_study_count": w.case_studies.count(),
        "case_study_building": sorted(getattr(w, "_building_case_studies", set())),
        "use_examples": getattr(w, "use_examples", True),
        "examples_count": w.examples_library.count,
        "examples_building": w.examples_library.is_building,
        "examples_build_progress": list(w.examples_library.build_progress),
        "examples_built_at": w.examples_library.built_at,
        "receptiveness": w.store.load_meta(w.current_contact).get("receptiveness", 5) if w.current_contact else 5,
        "locked_extra_context": (
            w.store.load_meta(w.current_contact).get("locked_extra_context", "")
            if w.current_contact else ""
        ),
        "global_extra_context": w.global_settings.global_extra_context,
        "custom_reply_system_prompt": getattr(
            w.global_settings, "custom_reply_system_prompt", ""
        ),
        # Factory default — never changes. Sent so the editor modal can
        # offer a one-click "Reset to original" that knows what the
        # baseline was even if the user overrode it weeks ago.
        "default_reply_system_prompt": REPLY_SYSTEM_PROMPT,
        "unread_replies": [u for u in w.unread_replies if u and u != "Unknown"],
        "reply_history_count": len(w._reply_history),
        "reply_history_index": w._reply_history_index,
        "reply_history_modes": [
            (h.get("mode") if isinstance(h, dict) else "")
            for h in (w._reply_history or [])
        ],
        # Applied case studies for the CURRENT history entry only
        # (each entry carries its own list; we surface just the active
        # one to keep the state payload small). Empty list when no
        # lessons were applied to this generation.
        "applied_case_studies": (
            (w._reply_history or [])[w._reply_history_index].get("applied_case_studies", [])
            if (w._reply_history and 0 <= w._reply_history_index < len(w._reply_history)
                and isinstance(w._reply_history[w._reply_history_index], dict))
            else []
        ),
        "applied_examples": (
            (w._reply_history or [])[w._reply_history_index].get("applied_examples", [])
            if (w._reply_history and 0 <= w._reply_history_index < len(w._reply_history)
                and isinstance(w._reply_history[w._reply_history_index], dict))
            else []
        ),
        "rapid_fire_active": w.rapid_fire.is_active,
        "rapid_fire_detected": len(w.rapid_fire.detected),
    }


async def _poll_loop():
    last_sv, last_tv, last_rv = -1, -1, -1
    while True:
        await asyncio.sleep(0.3)
        if not wingman:
            continue
        if wingman.status_version != last_sv:
            last_sv = wingman.status_version
            await broadcast({"type": "status", **_state()})
        if wingman.transcript_version != last_tv:
            last_tv = wingman.transcript_version
            await broadcast({"type": "transcript", "messages": wingman.conversation.to_display_list()})
        if wingman.replies_version != last_rv:
            last_rv = wingman.replies_version
            await broadcast({
                "type": "replies",
                "replies_version": wingman.replies_version,
                "options": wingman.latest_replies,
                "read": wingman.latest_read,
                "advice": wingman.latest_advice,
                "contact": wingman.current_contact,
            })


@asynccontextmanager
async def lifespan(app: FastAPI):
    global wingman
    if HEADLESS:
        wingman = Wingman(headless=True)
    else:
        from wingman.capture import CaptureRegion
        wingman = Wingman(capture_region=CaptureRegion())
    async def _on_reply_chunk(accumulated_text: str, contact: str = ""):
        await broadcast({"type": "reply_chunk", "text": accumulated_text, "contact": contact})

    wingman.on_reply_chunk = _on_reply_chunk
    tasks = [asyncio.create_task(wingman.run()), asyncio.create_task(_poll_loop())]
    print(
        f"[server] Open http://127.0.0.1:{SERVER_PORT}/ in your browser "
        f"(not a file:// page). Export: GET /api/export/bundle"
    )
    yield
    wingman.capture.stop()
    wingman.live.stop()
    for t in tasks:
        t.cancel()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the multi-tenant SaaS API when WINGMAN_MODE=saas. In personal
# mode (default) this is dormant and the desktop pipeline runs alone.
# Both modes can run simultaneously — the SaaS routes live under
# /api/v1/* and don't touch the existing desktop endpoints.
from wingman.saas import SAAS_MODE
if SAAS_MODE:
    from wingman.saas import db as _saas_db
    from wingman.saas.routes import router as _saas_router
    _saas_db.init_db()
    app.include_router(_saas_router)
    print("[saas] Multi-tenant API mounted at /api/v1")


@app.middleware("http")
async def allow_web_notifications(request: Request, call_next):
    """Ensure Notifications API is not blocked by a missing Permissions-Policy (some hosts default-deny)."""
    response = await call_next(request)
    if not any(k.lower() == "permissions-policy" for k in response.headers.keys()):
        response.headers["Permissions-Policy"] = "notifications=(self)"
    return response


@app.get("/")
async def index():
    """Serve SPA; inject headless-only layout hooks when WINGMAN_HEADLESS is set (DO / Safari)."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    if HEADLESS:
        html = html.replace("<html lang=\"en\">", "<html lang=\"en\" class=\"headless-mobile\">", 1)
        inject = '  <link rel="stylesheet" href="/static/mobile.css?v=9">\n'
        html = html.replace("</head>", inject + "</head>", 1)
    return Response(content=html, media_type="text/html")


@app.get("/api/state")
async def api_state():
    if not wingman:
        return {}
    return {
        **_state(),
        "transcript": wingman.conversation.to_display_list(),
        "replies": wingman.latest_replies,
        "read": wingman.latest_read,
        "advice": wingman.latest_advice,
    }


TRAINING_EXPORT_EXTS = frozenset({".txt", ".md", ".text", ".csv", ".json", ".srt", ".vtt"})


def _collect_training_files_export() -> list[dict]:
    from wingman.training import TRAINING_DIR

    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for fp in sorted(TRAINING_DIR.iterdir()):
        if fp.is_file() and fp.suffix.lower() in TRAINING_EXPORT_EXTS:
            try:
                out.append({"name": fp.name, "content": fp.read_text(encoding="utf-8", errors="replace")})
            except Exception as exc:
                print(f"[export] skip {fp}: {exc}")
    return out


def _collect_chats_export() -> list[dict]:
    from wingman.chat_store import STORE_DIR

    STORE_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for fp in sorted(STORE_DIR.glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            out.append({"contact": data.get("contact", fp.stem), "messages": data.get("messages", [])})
        except Exception as exc:
            print(f"[export] skip chat {fp}: {exc}")
    return out


def _export_presets_only() -> dict:
    if not wingman:
        return {"presets": [], "active_preset": -1}
    return {"presets": wingman.presets.presets, "active_preset": wingman.active_preset}


def _is_full_bundle(body: dict) -> bool:
    if body.get("wingman_bundle_version") == 1:
        return True
    if "training_files" in body or "chats" in body:
        return True
    return False


def _clear_training_for_import() -> None:
    from wingman.training import TRAINING_DIR

    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    for fp in TRAINING_DIR.iterdir():
        if fp.is_file() and fp.suffix.lower() in TRAINING_EXPORT_EXTS:
            try:
                fp.unlink()
            except Exception:
                pass


def _clear_chats_for_import() -> None:
    from wingman.chat_store import STORE_DIR

    STORE_DIR.mkdir(parents=True, exist_ok=True)
    for fp in STORE_DIR.glob("*.json"):
        try:
            fp.unlink()
        except Exception:
            pass


def _apply_full_bundle(body: dict) -> dict:
    w = wingman
    assert w is not None
    _clear_training_for_import()
    _clear_chats_for_import()
    presets = body.get("presets", [])
    if isinstance(presets, list):
        w.presets.replace_all(presets)
    ap = body.get("active_preset", -1)
    try:
        ap = int(ap)
    except (TypeError, ValueError):
        ap = -1
    n = len(w.presets.presets)
    if n == 0:
        w.active_preset = -1
    elif ap < 0 or ap >= n:
        w.active_preset = -1
    else:
        w.active_preset = ap

    from wingman.training import TRAINING_DIR

    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    for item in body.get("training_files") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name or not isinstance(name, str):
            continue
        safe = Path(str(name)).name
        if not safe or safe.startswith("."):
            continue
        content = item.get("content", "")
        (TRAINING_DIR / safe).write_text(str(content), encoding="utf-8")

    if w.training.load():
        w.generator.set_cache(w.training.cache_name, training_cache=w.training)

    for ch in body.get("chats") or []:
        if not isinstance(ch, dict):
            continue
        contact = str(ch.get("contact", "imported")).strip() or "imported"
        messages = ch.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        w.store.save_raw(contact, messages)
    w.saved_contacts = w.store.list_contacts()
    w._bump()
    return {
        "ok": True,
        "presets_count": n,
        "training_files": len(body.get("training_files") or []),
        "chats_count": len(body.get("chats") or []),
        "active_preset": w.active_preset,
    }


def _unwrap_json_body(body: Any) -> Any:
    """If the client double-encoded JSON (body is a string), parse once more."""
    if isinstance(body, str) and body.strip():
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return body
    return body


def apply_import_payload(body: Any) -> dict:
    """Import goals-only export, raw presets array, or full wingman bundle."""
    if not wingman:
        return {"error": "Wingman not ready"}
    if body is None:
        return {"error": "Empty file — pick wingman-bundle.json from Export"}

    body = _unwrap_json_body(body)

    if isinstance(body, list):
        wingman.presets.replace_all(body)
        wingman.active_preset = -1
        wingman._bump()
        return {"ok": True, "count": len(wingman.presets.presets), "active_preset": -1}
    if not isinstance(body, dict):
        return {
            "error": "Expected a JSON object or array — open the file in a text editor and confirm it starts with { or [",
        }

    if body.get("detail") and "presets" not in body:
        return {
            "error": "This file looks like a server error (e.g. Not Found), not an export. Run Export again from http://127.0.0.1:8000",
        }

    if _is_full_bundle(body):
        return _apply_full_bundle(body)
    raw = body.get("presets")
    if not isinstance(raw, list):
        return {
            "error": "Missing \"presets\" array — use Export to download wingman-bundle.json, or a goals file with { \"presets\": [...], \"active_preset\": n }",
        }
    wingman.presets.replace_all(raw)
    ap = body.get("active_preset", -1)
    try:
        ap = int(ap)
    except (TypeError, ValueError):
        ap = -1
    n = len(wingman.presets.presets)
    if n == 0:
        wingman.active_preset = -1
    elif ap < 0 or ap >= n:
        wingman.active_preset = -1
    else:
        wingman.active_preset = ap
    wingman._bump()
    return {"ok": True, "count": n, "active_preset": wingman.active_preset}


@app.get("/api/export/bundle")
async def api_export_bundle():
    """Full backup: goals, training transcript files, and saved chats (JSON)."""
    if not wingman:
        return {
            "wingman_bundle_version": 1,
            "presets": [],
            "active_preset": -1,
            "training_files": [],
            "chats": [],
        }
    return {
        "wingman_bundle_version": 1,
        "presets": wingman.presets.presets,
        "active_preset": wingman.active_preset,
        "training_files": _collect_training_files_export(),
        "chats": _collect_chats_export(),
    }


@app.get("/api/export/presets")
async def api_export_presets():
    """Goals only (smaller file)."""
    return _export_presets_only()


@app.get("/api/presets-export")
async def api_export_presets_legacy_path():
    """Legacy path — same as /api/export/presets (some proxies mis-handle hyphenated paths)."""
    return _export_presets_only()


@app.post("/api/import/bundle")
@app.post("/api/presets-import")
async def api_import_any(body: Any = Body(...)):
    """Import full bundle, goals-only export, or raw presets array."""
    return apply_import_payload(body)


@app.post("/api/upload-training")
async def upload_training(files: list[UploadFile] = File(...)):
    """Upload training transcript files."""
    from wingman.training import TRAINING_DIR
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        content = await f.read()
        path = TRAINING_DIR / f.filename
        path.write_bytes(content)
        saved.append(f.filename)
        print(f"[server] Saved training file: {f.filename} ({len(content):,} bytes)")

    if wingman and saved:
        success = wingman.training.load()
        if success:
            wingman.generator.set_cache(wingman.training.cache_name)
        wingman._bump()

    return {"saved": saved, "training_status": wingman.training.status if wingman else "unknown"}


@app.post("/api/upload-screenshots")
async def upload_screenshots(
    files: list[UploadFile] = File(...),
    contact: str = Form(""),
    extra_context: str = Form(""),
):
    """Upload chat screenshots and/or videos."""
    if not wingman:
        return {"error": "Wingman not ready"}

    if wingman.status in ("processing", "generating"):
        return {"error": "Already processing — wait for current analysis to finish"}

    from wingman.chat_reader import ChatReader
    media_items: list[tuple[bytes, str]] = []
    for f in files:
        data = await f.read()
        mime = ChatReader.detect_mime(f.filename or "", data)
        media_items.append((data, mime))
        print(f"[server] Received: {f.filename} ({len(data):,} bytes, {mime})")

    if not media_items:
        return {"error": "No files uploaded"}

    asyncio.create_task(
        wingman.process_media(contact, media_items, extra_context)
    )

    return {
        "status": "processing",
        "files": len(media_items),
        "contact": contact or "Unknown",
    }


@app.get("/frame.jpg")
async def latest_frame():
    if wingman and wingman.latest_frame_b64:
        return Response(content=base64.b64decode(wingman.latest_frame_b64), media_type="image/jpeg")
    return Response(content=b"", status_code=204)


_quick_lock: asyncio.Lock | None = None


def _get_quick_lock() -> asyncio.Lock:
    global _quick_lock
    if _quick_lock is None:
        _quick_lock = asyncio.Lock()
    return _quick_lock


@app.post("/api/quick-capture")
async def quick_capture(
    contact: str = Form(""),
    extra_context: str = Form(""),
    auto_detect: str = Form(""),
    image_b64: str = Form(""),
):
    """Take the current screen frame, extract messages, store image, and generate replies.

    When ``auto_detect`` is truthy (e.g. global hotkey), the contact name is
    ALWAYS extracted from the screenshot itself, ignoring whichever chat the
    user happens to have open in the UI. Without that flag, behaviour is the
    original UI-button path: fall back to the current contact so context adds
    to whatever chat is being viewed.

    If ``image_b64`` is provided, that JPEG is used (hotkey sends its own
    freshly captured frame to avoid races with the continuous-capture
    buffer). Otherwise the server's latest cached frame is used (UI button).
    """
    if not wingman:
        return {"error": "Not ready"}
    if image_b64:
        try:
            frame_bytes = base64.b64decode(image_b64)
        except Exception:
            return {"error": "invalid image_b64"}
    elif wingman.latest_frame_b64:
        frame_bytes = base64.b64decode(wingman.latest_frame_b64)
    else:
        return {"error": "No screen frame available"}

    auto = bool(auto_detect)
    explicit_contact = contact.strip()
    if auto:
        capture_contact = explicit_contact or "__autodetect__"
    else:
        capture_contact = explicit_contact or wingman.current_contact or "Unknown"

    async def _extract_in_background(fb):
        """Flash extracts messages — saves to disk. Refreshes live transcript only if still on same chat."""
        try:
            result = await wingman.reader.read(fb)
            if result.messages:
                from wingman.transcript import ConversationState
                conv = ConversationState()
                existing = wingman.store.load(capture_contact)
                if existing:
                    conv.ingest_parsed_messages(existing)
                added = conv.ingest_parsed_messages(result.messages)
                if added:
                    wingman.store.save(capture_contact, conv.messages)
                    wingman.saved_contacts = wingman.store.list_contacts()
                    print(f"[quick] +{added} messages extracted for {capture_contact}")
                    # Refresh live transcript if user is still on this chat
                    if capture_contact == wingman.current_contact:
                        wingman.conversation.messages.clear()
                        wingman.conversation.ingest_parsed_messages(
                            wingman.store.load(capture_contact)
                        )
                        wingman.transcript_version += 1
                    wingman.status_version += 1
        except Exception as exc:
            print(f"[quick] Background extraction failed: {exc}")

    async def _process():
        nonlocal capture_contact
        if auto:
            c = explicit_contact  # ignore current_contact on hotkey path
        else:
            c = explicit_contact or wingman.current_contact or ""

        if not c:
            print(
                "[quick] Auto-detect mode — extracting contact from screenshot..."
                if auto else
                "[quick] No contact name — extracting from screenshot..."
            )
            try:
                from wingman.config import (
                    FLASH_MODEL, FLASH_LITE_MODEL, RAPID_FIRE_PROMPT,
                    make_genai_client, rotate_api_key, _ALL_KEYS,
                )
                from google.genai import types as gtypes
                image_part = gtypes.Part.from_bytes(data=frame_bytes, mime_type="image/jpeg")
                # RAPID_FIRE_PROMPT is named after Rapid Fire mode (the
                # video multi-chat feature) but the extraction format it
                # asks for — {contact, platform, messages} — is exactly
                # what we need for a single hotkey screenshot too. Legacy
                # name, not a semantic mismatch.
                #
                # max_output_tokens bumped 4096 -> 8192 because Flash was
                # truncating its JSON mid-response on chats with 15+
                # visible messages, producing 'Name extraction failed:
                # Unterminated string...' and aborting the whole capture.
                flash_cfg = gtypes.GenerateContentConfig(
                    temperature=0.1, max_output_tokens=8192,
                    response_mime_type="application/json",
                )

                # Prefer Flash Lite for extraction (2x faster than full
                # Flash, already multimodal, already used by the matcher
                # adjudicator). Fall back to Flash on any 404/unavailable
                # so we can't regress if Lite misbehaves on vision.
                _model_order = [FLASH_LITE_MODEL, FLASH_MODEL]
                resp = None
                last_flash_err = None
                for extract_model in _model_order:
                    extract_this_model_ok = False
                    # Rotate through keys on 429 so a single dead key
                    # doesn't make auto-detect report "couldn't detect".
                    for flash_attempt in range(max(1, len(_ALL_KEYS))):
                        try:
                            client = make_genai_client()
                            resp = await asyncio.to_thread(
                                client.models.generate_content,
                                model=extract_model,
                                contents=[RAPID_FIRE_PROMPT, image_part],
                                config=flash_cfg,
                            )
                            extract_this_model_ok = True
                            break
                        except Exception as flash_exc:
                            last_flash_err = flash_exc
                            msg = str(flash_exc)
                            is_404 = "404" in msg or "NOT_FOUND" in msg or "not found" in msg.lower()
                            if is_404 and extract_model == FLASH_LITE_MODEL:
                                print(f"[quick] {FLASH_LITE_MODEL} unavailable, falling back to {FLASH_MODEL}")
                                break  # break key-rotation loop, outer will try Flash
                            if ("429" in msg or "RESOURCE_EXHAUSTED" in msg) and flash_attempt < len(_ALL_KEYS) - 1:
                                rotate_api_key()
                                print(f"[quick] Flash extraction rate-limited, rotated key")
                                await asyncio.sleep(0.5)
                                continue
                            # Non-retryable / out of keys — bubble up
                            raise
                    if extract_this_model_ok:
                        break  # success, don't try the next model

                import json as _json
                data = _json.loads((resp.text if resp else "") or "{}")
                extracted_name = (data.get("contact") or "").strip()
                extracted_msgs = data.get("messages") or []
                platform = (data.get("platform") or "").strip().lower()
                if platform in ("other", "unknown", "none"):
                    platform = ""
                proposed = f"{platform} - {extracted_name}" if (extracted_name and platform) else (extracted_name or "")

                # Run the local (fast) matcher first.
                tx_match, tx_score = _match_by_transcript_overlap(
                    extracted_msgs, wingman.saved_contacts, wingman.store
                )

                # Decide if the local match is strong enough to trust
                # without consulting Flash Lite (the fast path).
                strong = False
                if tx_match:
                    try:
                        from thefuzz import fuzz as _fz
                        screenshot_texts = _msg_texts(extracted_msgs, _SCREENSHOT_TAIL)
                        saved_texts = _msg_texts(wingman.store.load(tx_match) or [], _SAVED_TAIL)
                        strong = _is_strong_local_match(screenshot_texts, saved_texts, _fz, tx_score)
                    except Exception:
                        strong = False

                if tx_match and strong:
                    # Tier 1: clearly the same conversation — zero Flash calls.
                    c = tx_match
                    capture_contact = c
                    print(f"[quick] fast_merge -> {c} (local={tx_score}/100)")
                elif extracted_name and (tx_match or _name_collides(proposed, wingman.saved_contacts)):
                    # Tier 2: borderline OR same-base-name collision → Flash Lite
                    # adjudicates using conversation semantics, not just fuzzy text.
                    candidates = _gather_candidates(
                        proposed, tx_match, tx_score,
                        wingman.saved_contacts, wingman.store,
                    )
                    if candidates:
                        print(f"[quick] adjudicating vs {len(candidates)} candidate(s): "
                              f"{[n for n,_ in candidates]} (local best={tx_match or '-'} {tx_score}/100)")
                        try:
                            from wingman.match_adjudicator import adjudicate_match
                            chosen, reason = await adjudicate_match(
                                extracted_msgs, candidates, extracted_name, platform,
                            )
                        except Exception as exc:
                            print(f"[adjudicator] fatal: {exc}")
                            chosen, reason = "", f"adjudicator crashed: {exc}"
                        if chosen:
                            c = chosen
                            capture_contact = c
                            print(f"[quick] flash_merge -> {c} ({reason})")
                        else:
                            c = _disambiguate_name(proposed, wingman.saved_contacts, store=wingman.store)
                            capture_contact = c
                            print(f"[quick] flash_new -> {c} ({reason})")
                    else:
                        # No candidates to show Flash — just create.
                        c = _disambiguate_name(proposed, wingman.saved_contacts, store=wingman.store)
                        capture_contact = c
                        print(f"[quick] bare_new -> {c} (no candidates; local={tx_score}/100)")
                elif extracted_name:
                    # Tier 3: no decent local match, no same-name collision
                    # — clear new chat, no Flash needed.
                    c = _disambiguate_name(proposed, wingman.saved_contacts, store=wingman.store)
                    capture_contact = c
                    print(f"[quick] bare_new -> {c} (local={tx_score}/100)")
                else:
                    # No name extracted — transcript overlap is the only chance.
                    if tx_match:
                        c = tx_match
                        capture_contact = c
                        print(f"[quick] fast_merge (no-name) -> {c} (local={tx_score}/100)")
                    else:
                        c = ""  # bail below — don't create junk "Unknown" chats
            except Exception as exc:
                print(f"[quick] Name extraction failed: {exc}")
                c = ""

        # Auto-detect couldn't identify a chat — abort quietly with a
        # notification instead of polluting the store with an "Unknown"
        # entry and firing a misleading toast.
        if auto and not c:
            print("[quick] Aborting — could not identify chat from screenshot")
            try:
                from wingman.notify import notify as _notify
                _notify("Wingman", "Couldn't detect the chat — try again or open Wingman to select manually.")
            except Exception:
                pass
            wingman.status = "idle"
            wingman._bump()
            return

        # Safety net for the UI-button path (non-auto): if we still have
        # no contact here, fall back to the legacy "Unknown" bucket so
        # behaviour matches what shipped before the hotkey changes.
        if not c:
            c = "Unknown"
            capture_contact = c

        from wingman.transcript import ConversationState
        local_conv = ConversationState()
        existing = wingman.store.load(c)
        if existing:
            local_conv.ingest_parsed_messages(existing)

        if not existing:
            wingman.store.save(c, local_conv.messages)
            wingman.saved_contacts = wingman.store.list_contacts()
            wingman._bump()

        wingman.latest_screenshots = [frame_bytes]

        # Dedupe the extraction API call. On the auto-detect path
        # we ALREADY extracted messages from this same screenshot
        # via RAPID_FIRE_PROMPT above — running `_extract_in_background`
        # would make a second Flash call (CHAT_READER_PROMPT) on the
        # exact same image for the exact same data. Save those messages
        # directly to disk instead, skip the second round-trip.
        # For the non-auto path (UI Quick Capture button, where contact
        # is already known but messages aren't extracted yet), fall back
        # to the background extraction call.
        extract_task = None
        if auto and 'extracted_msgs' in locals() and extracted_msgs:
            try:
                msgs_conv = ConversationState()
                existing_for_save = wingman.store.load(c) or []
                if existing_for_save:
                    msgs_conv.ingest_parsed_messages(existing_for_save)
                added = msgs_conv.ingest_parsed_messages(extracted_msgs)
                if added:
                    wingman.store.save(c, msgs_conv.messages)
                    wingman.saved_contacts = wingman.store.list_contacts()
                    print(f"[quick] +{added} messages saved for {c} (reused RAPID_FIRE extraction)")
                    if c == wingman.current_contact:
                        wingman.conversation.messages.clear()
                        wingman.conversation.ingest_parsed_messages(
                            wingman.store.load(c)
                        )
                        wingman.transcript_version += 1
                    wingman.status_version += 1
                # Refresh local_conv so downstream generation sees the new msgs
                local_conv.messages.clear()
                local_conv.ingest_parsed_messages(wingman.store.load(c))
            except Exception as exc:
                print(f"[quick] Direct save from RAPID_FIRE failed ({exc}), falling back to Flash extraction")
                extract_task = asyncio.create_task(_extract_in_background(frame_bytes))
        else:
            extract_task = asyncio.create_task(_extract_in_background(frame_bytes))

        wingman.status = "generating"
        wingman._bump()
        print(f"[quick] Generating replies for {c}")

        if local_conv.messages:
            await _generate_for_contact_isolated(c, local_conv, extra_context)
        elif extract_task is not None:
            print("[quick] No existing messages, waiting for extraction...")
            await extract_task
            reloaded = wingman.store.load(c)
            if reloaded:
                local_conv.messages.clear()
                local_conv.ingest_parsed_messages(reloaded)
            if local_conv.messages:
                await _generate_for_contact_isolated(c, local_conv, extra_context)
            else:
                wingman.status = "idle"
                wingman._bump()

    async def _generate_for_contact_isolated(contact_name, conv, extra_ctx):
        """Generate replies for a contact using a DIRECT API call — no shared lock."""
        import time as _time
        import json as _json
        from wingman.conversation_summary import summarize_if_needed
        from wingman.config import (
            PRO_MODEL, FLASH_MODEL,
            REPLY_SYSTEM_PROMPT, REPLY_SYSTEM_PROMPT_SAFE,
            make_genai_client,
        )
        from google.genai import types as gtypes

        msg_count = len(conv.messages)
        summary, recent_json = await asyncio.to_thread(
            summarize_if_needed, conv.messages, contact_name,
        )
        if summary:
            transcript = f"[CONVERSATION SUMMARY]\n{summary}\n\n[RECENT MESSAGES]\n{recent_json}"
        else:
            transcript = recent_json

        use_flash = wingman.reply_model == "flash"
        model = FLASH_MODEL if use_flash else PRO_MODEL
        tag = "flash" if use_flash else "pro"
        knowledge = wingman.training_rag.knowledge_summary if wingman.use_training and wingman.training_rag.status == "loaded" else ""
        time_ctx = conv.time_context()
        meta = wingman.store.load_meta(contact_name)
        recep = meta.get("receptiveness", 5)
        preset_idx = meta.get("active_preset", wingman.default_preset)
        goal = wingman.presets.get(preset_idx) if preset_idx >= 0 else ""

        # Extra-context layers: global → per-chat locked → one-shot.
        # See wingman/main.py:_generate_replies for the same stacking
        # rule. The hotkey user never touches the web UI so both sticky
        # layers must still apply automatically.
        global_ctx = ""
        try:
            global_ctx = (wingman.global_settings.global_extra_context or "").strip()
        except Exception:
            global_ctx = ""
        locked_ctx = (meta.get("locked_extra_context") or "").strip()
        pieces = [p for p in (global_ctx, locked_ctx, (extra_ctx or "").strip()) if p]
        extra_ctx = "\n\n".join(pieces)
        if extra_ctx and not goal:
            goal = extra_ctx

        # User custom baseline prompt (from the in-app editor). Falls
        # back to the hardcoded REPLY_SYSTEM_PROMPT when empty. Mirrors
        # the override logic in wingman.reply_generator so both paths
        # (Regenerate + hotkey/quick capture) behave identically.
        _custom_sys = ""
        try:
            _custom_sys = (wingman.global_settings.custom_reply_system_prompt or "").strip()
        except Exception:
            _custom_sys = ""
        _base_sys_source = _custom_sys or REPLY_SYSTEM_PROMPT
        system_parts = [_base_sys_source.split("Conversation:\n{transcript}")[0].rstrip()]
        if knowledge:
            system_parts.append(knowledge)

        # Examples Library retrieval (positive style anchors) — runs
        # alongside case studies. Same architecture, different polarity.
        examples_block = ""
        applied_examples: list[dict] = []
        if (
            getattr(wingman, "use_examples", True)
            and not wingman.examples_library.is_empty
        ):
            try:
                from wingman.examples_library import retrieve_examples_for_live_chat
                ex_hits, examples_block = await retrieve_examples_for_live_chat(
                    wingman.examples_library,
                    [m.to_dict() for m in conv.messages],
                    exclude_contact=contact_name or "",
                    top_k=4, min_similarity=0.60,
                )
                if ex_hits:
                    applied_examples = [
                        {"contact": e.contact,
                         "similarity": round(float(s), 3),
                         "reply": e.reply}
                        for s, e in ex_hits
                    ]
                    print(f"[quick] Examples injected: "
                          f"{', '.join(e.contact for _, e in ex_hits)} "
                          f"(top {ex_hits[0][0]:.2f})")
            except Exception as exc:
                import traceback
                print(f"[quick] Examples retrieval failed (non-fatal): {exc}")
                traceback.print_exc()
        if examples_block:
            system_parts.append(examples_block)

        # Case Study Library retrieval for the hotkey/quick-capture path.
        # Mirrors what wingman.main._generate_replies does so the hotkey
        # gets the same learned lessons. No-op when store is empty.
        case_studies_block = ""
        applied_case_studies: list[dict] = []
        if (
            getattr(wingman, "use_lessons", True)
            and not wingman.case_studies.is_empty()
        ):
            try:
                from wingman.case_studies import retrieve_case_studies_for_live_chat
                hits, case_studies_block = await retrieve_case_studies_for_live_chat(
                    wingman.case_studies,
                    [m.to_dict() for m in conv.messages],
                    exclude_contact=contact_name or "",
                    top_k=3, min_similarity=0.55,
                )
                if hits:
                    applied_case_studies = [
                        {"contact": e.contact, "similarity": round(float(s), 3)}
                        for s, e in hits
                    ]
                    names = ", ".join(e.contact for _, e in hits)
                    print(f"[quick] Case studies injected: {names} (top {hits[0][0]:.2f})")
            except Exception as exc:
                import traceback
                print(f"[quick] Case study retrieval failed (non-fatal): {exc}")
                traceback.print_exc()
        if case_studies_block:
            system_parts.append(case_studies_block)

        user_parts = []
        if time_ctx:
            user_parts.append(time_ctx)
        user_parts.append(f"Conversation:\n{transcript}")
        if goal:
            user_parts.append(f"My goal for this chat: {goal}")
        if extra_ctx:
            user_parts.append(f"Additional context: {extra_ctx}")
        user_parts.append(
            "Format as JSON:\n"
            "{\"read\": \"...\", \"advice\": \"...\", \"replies\": ["
            "{\"label\": \"...\", \"text\": \"...\", \"why\": \"...\"}]}"
        )
        prompt_text = "\n\n".join(user_parts)

        contents = [prompt_text]
        if frame_bytes:
            contents.append(gtypes.Part.from_bytes(data=frame_bytes, mime_type="image/jpeg"))

        # 32k for Pro so thinking tokens (especially with long goals +
        # lessons block) don't starve the JSON output. Matches the
        # Regenerate path in wingman/reply_generator.py.
        max_tokens = 32768 if not use_flash else 4096
        from wingman.config import permissive_safety_settings
        config = gtypes.GenerateContentConfig(
            system_instruction="\n\n".join(system_parts),
            temperature=0.9,
            max_output_tokens=max_tokens,
            safety_settings=permissive_safety_settings(),
        )

        try:
            _sys_chars = sum(len(p) for p in system_parts)
            _usr_chars = len(prompt_text)
            _cs_chars = len(case_studies_block or "")
            _ex_chars = len(examples_block or "")
            _kb_chars = len(knowledge or "")
            print(
                f"[quick] Prompt size: system={_sys_chars}c "
                f"(playbook={_kb_chars}c, examples={_ex_chars}c, "
                f"lessons={_cs_chars}c) "
                f"user={_usr_chars}c images={1 if frame_bytes else 0}"
            )
        except Exception:
            pass
        print(f"[quick] Generating for {contact_name} with {tag} (isolated)...")
        try:
            from wingman.config import _ALL_KEYS, rotate_api_key
            client = make_genai_client()

            # Initialize EVERY state variable before we branch so the
            # Google retry loop below has something coherent to inspect
            # whether KIE ran or not. Forgetting this caused an
            # UnboundLocalError on every hotkey capture in the last build.
            accumulated = ""
            succeeded = False
            last_err = None
            total_attempts = 0
            max_key_attempts = max(1, len(_ALL_KEYS))
            max_overload_retries = 3
            overload_retries = 0

            # If the user has flipped the Grok toggle on AND we're on Pro,
            # route this generation through xAI's API (multi-agent by
            # default — Lucas participates). Same fallback rules as KIE.
            # Tuned model routing — highest priority in the hotkey
            # path so reply_model="tuned" captures actually hit the
            # fine-tuned endpoint instead of falling through to Pro.
            # Same 5-parallel hedge pattern as the Regenerate button.
            route_via_tuned = (
                wingman.reply_model == "tuned"
                and not use_flash
            )
            if route_via_tuned:
                try:
                    from wingman.tuned_flash_client import (
                        generate_tuned_replies_json, is_tuned_configured,
                    )
                    if is_tuned_configured():
                        async def _tuned_cb(text: str):
                            if contact_name == wingman.current_contact:
                                await broadcast({
                                    "type": "reply_chunk",
                                    "text": text,
                                    "contact": contact_name,
                                })
                        # Use the isolated conversation's raw messages —
                        # the tuned model was trained on situation text,
                        # not on the Pro JSON prompt format. Passing
                        # conv.messages keeps the prompt in-distribution.
                        tuned_msgs = [m.to_dict() for m in conv.messages]
                        print(f"[quick] Routing via Tuned Flash "
                              f"(5 parallel calls)")
                        accumulated = await generate_tuned_replies_json(
                            tuned_msgs,
                            goal=goal,
                            extra_context=extra_ctx,
                            on_chunk=_tuned_cb,
                            timeout_s=15,
                        )
                        succeeded = bool(accumulated.strip())
                        if succeeded:
                            print(f"[quick] Tuned Flash complete: "
                                  f"{len(accumulated)} chars")
                    else:
                        print("[quick] reply_model=tuned but endpoint "
                              "missing — falling back")
                except Exception as tuned_exc:
                    import traceback
                    print(f"[quick] Tuned Flash failed ({tuned_exc}) "
                          f"— falling back to Google direct")
                    traceback.print_exc()
                    accumulated = ""
                    succeeded = False

            route_via_grok = (
                not succeeded  # don't run Grok if Tuned already produced
                and bool(getattr(wingman, "use_grok", False))
                and not use_flash
            )
            if route_via_grok:
                try:
                    from wingman.grok_client import (
                        generate_grok_stream, is_grok_configured,
                    )
                    if is_grok_configured():
                        async def _grok_chunk_cb(text: str):
                            if contact_name == wingman.current_contact:
                                await broadcast({"type": "reply_chunk", "text": text, "contact": contact_name})
                        grok_mode = getattr(wingman, "grok_mode", "multi-agent")
                        # Rebuild system instruction to include the full
                        # training corpus BEFORE case_studies (stable
                        # prefix for xAI prompt cache). Mirrors the
                        # reply_generator.py path so cache hits are
                        # shared between Regenerate + hotkey captures.
                        grok_sys_parts = [
                            REPLY_SYSTEM_PROMPT.split(
                                "Conversation:\n{transcript}"
                            )[0].rstrip()
                        ]
                        if knowledge:
                            grok_sys_parts.append(knowledge)
                        grok_corpus_text = ""
                        if (
                            getattr(wingman, "grok_full_training", False)
                            and not wingman.training_corpus.is_empty
                        ):
                            grok_corpus_text = wingman.training_corpus.text
                            grok_sys_parts.append(grok_corpus_text)
                        if examples_block:
                            grok_sys_parts.append(examples_block)
                        if case_studies_block:
                            grok_sys_parts.append(case_studies_block)
                        grok_system_instruction = "\n\n".join(grok_sys_parts)
                        corpus_tag = (
                            f", +corpus={len(grok_corpus_text)//1000}kc"
                            if grok_corpus_text else ""
                        )
                        print(f"[quick] Routing via Grok ({grok_mode}{corpus_tag})")
                        accumulated = await generate_grok_stream(
                            system_instruction=grok_system_instruction,
                            user_text=prompt_text,
                            images=[frame_bytes] if frame_bytes else None,
                            on_chunk=_grok_chunk_cb,
                            mode=grok_mode,
                            cache_key="wingman-training-v1",
                            timeout_s=240,
                        )
                        succeeded = bool(accumulated.strip())
                        if succeeded:
                            print(f"[quick] Grok complete: {len(accumulated)} chars")
                    else:
                        print("[quick] use_grok=on but XAI_API_KEY missing — falling back")
                except Exception as grok_exc:
                    print(f"[quick] Grok failed ({grok_exc}) — falling back to Google direct")
                    accumulated = ""
                    succeeded = False

            # If the user has flipped the KIE toggle on AND we're on Pro,
            # route this generation through KIE instead of Google direct.
            # Flash always stays on Google (KIE only offers Pro). Falls
            # back to direct on any KIE error so toggling it on is safe.
            route_via_kie = (
                not succeeded  # don't run KIE when Grok already produced output
                and bool(getattr(wingman, "use_kie", False))
                and not use_flash
            )
            if route_via_kie:
                try:
                    from wingman.kie_client import generate_kie_stream
                    async def _chunk_cb(text: str):
                        if contact_name == wingman.current_contact:
                            await broadcast({"type": "reply_chunk", "text": text, "contact": contact_name})
                    print(f"[quick] Routing via KIE (use_kie=on)")
                    accumulated = await generate_kie_stream(
                        system_instruction="\n\n".join(system_parts),
                        user_text=prompt_text,
                        images=[frame_bytes] if frame_bytes else None,
                        on_chunk=_chunk_cb,
                        timeout_s=120,
                    )
                    succeeded = bool(accumulated.strip())
                    if succeeded:
                        print(f"[quick] KIE complete: {len(accumulated)} chars")
                except Exception as kie_exc:
                    print(f"[quick] KIE failed ({kie_exc}) — falling back to Google direct")
                    accumulated = ""
                    succeeded = False
            # Per-attempt timeouts. See wingman.reply_generator for
            # rationale. TTFT=20s kills dead keys fast, TOTAL=60s caps
            # runaway streams. On timeout we ROTATE to the next key
            # instead of retrying the same one (the old bug).
            TTFT_TIMEOUT = 20
            TOTAL_TIMEOUT = 60

            async def _consume_stream():
                nonlocal accumulated
                accumulated = ""
                chunk_count_local = 0
                first_token_deadline = asyncio.get_event_loop().time() + TTFT_TIMEOUT
                async for chunk in await client.aio.models.generate_content_stream(
                    model=model, contents=contents, config=config,
                ):
                    if chunk.text:
                        accumulated += chunk.text
                        chunk_count_local += 1
                        if contact_name == wingman.current_contact:
                            await broadcast({"type": "reply_chunk", "text": accumulated, "contact": contact_name})
                    if chunk_count_local == 0 and asyncio.get_event_loop().time() > first_token_deadline:
                        raise asyncio.TimeoutError(f"no first token within {TTFT_TIMEOUT}s")

            # Skip the Google retry loop entirely when KIE / Grok
            # already produced a response.
            while not succeeded and total_attempts < (max_key_attempts + max_overload_retries):
                total_attempts += 1
                try:
                    await asyncio.wait_for(_consume_stream(), timeout=TOTAL_TIMEOUT)
                    succeeded = True
                    break
                except asyncio.TimeoutError:
                    last_err = asyncio.TimeoutError(
                        f"stream hung (ttft={TTFT_TIMEOUT}s / total={TOTAL_TIMEOUT}s)"
                    )
                    # Rotate to the next key instead of retrying the
                    # hung one. This is the key fix for "replies taking
                    # 100+ seconds" on dead / capped keys.
                    if total_attempts < max_key_attempts:
                        rotate_api_key()
                        client = make_genai_client()
                        print(f"[quick] Stream hung — rotated to next key (attempt {total_attempts}/{max_key_attempts})")
                        continue
                    break
                except Exception as exc:
                    last_err = exc
                    err_str = str(exc)
                    is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                    is_overload = "503" in err_str or "UNAVAILABLE" in err_str or "high demand" in err_str.lower()
                    if is_rate_limit:
                        rotate_api_key()
                        client = make_genai_client()
                        print(f"[quick] Rate-limited on key, rotated (attempt {total_attempts})")
                        await asyncio.sleep(1)
                        continue
                    if is_overload and overload_retries < max_overload_retries:
                        overload_retries += 1
                        backoff = 2 ** overload_retries  # 2s, 4s, 8s
                        print(f"[quick] Pro overloaded (503), retrying in {backoff}s (retry {overload_retries}/{max_overload_retries})")
                        await asyncio.sleep(backoff)
                        continue
                    raise

            if not succeeded:
                err_txt = str(last_err)
                is_overload_final = "503" in err_txt or "UNAVAILABLE" in err_txt or "hung past" in err_txt
                print(f"[quick] Generation failed after {total_attempts} attempts: {err_txt[:200]}")
                # Surface the failure to the user so they know to switch to
                # Flash instead of silently getting no replies.
                try:
                    from wingman.notify import notify as _notify
                    if is_overload_final:
                        _notify("Wingman", f"Pro is overloaded for {contact_name} — try switching to Flash")
                    else:
                        _notify("Wingman", f"Generation failed for {contact_name} — see server log")
                except Exception:
                    pass

            from wingman.reply_generator import ReplyGenerator
            result = ReplyGenerator._parse_response(accumulated)

            # Fallback for AI-Studio PROHIBITED_CONTENT hard blocks (explicit
            # chats like Millie). The normal stream returns no text / no
            # candidates. We retry in two escalating steps:
            #   2. Safer-framing retry — reframe the system prompt as
            #      "output analysis JSON" rather than "coach → replies".
            #   3. Redacted retry — if (2) still blocked, replace explicit
            #      message bodies with a placeholder so the policy filter
            #      lets the prompt through, then regenerate from context.
            # Untouched for every non-blocked chat — those never hit this.
            if not result.replies and not accumulated.strip():
                safe_sys = REPLY_SYSTEM_PROMPT_SAFE.split("Conversation:\n{transcript}")[0].rstrip()
                safe_system_parts = [safe_sys]
                if knowledge:
                    safe_system_parts.append(knowledge)
                if examples_block:
                    safe_system_parts.append(examples_block)
                if case_studies_block:
                    safe_system_parts.append(case_studies_block)
                safe_config = gtypes.GenerateContentConfig(
                    system_instruction="\n\n".join(safe_system_parts),
                    temperature=0.9,
                    max_output_tokens=max_tokens,
                    safety_settings=permissive_safety_settings(),
                )
                print(f"[quick] Empty response — retrying {contact_name} with safe framing...")
                retry_block_reason = None
                retry_text = ""
                try:
                    retry_resp = await asyncio.to_thread(
                        client.models.generate_content,
                        model=model, contents=contents, config=safe_config,
                    )
                    try:
                        retry_block_reason = getattr(retry_resp.prompt_feedback, "block_reason", None)
                    except Exception:
                        pass
                    retry_text = (retry_resp.text or "").strip()
                    if retry_text:
                        accumulated = retry_text
                        result = ReplyGenerator._parse_response(accumulated)
                        if contact_name == wingman.current_contact:
                            await broadcast({"type": "reply_chunk", "text": accumulated, "contact": contact_name})
                        print(f"[quick] Safe-framing retry produced {len(result.replies)} replies")
                    else:
                        print(f"[quick] Safe-framing retry empty (block_reason={retry_block_reason})")
                except Exception as exc:
                    print(f"[quick] Safe-framing retry failed: {exc}")

                # Third tier: redacted retry — last-resort if the safe
                # retry is still blocked. Replaces explicit message bodies
                # with a '[explicit content]' placeholder so the gateway
                # accepts the prompt. Replies are inferred from context.
                if not result.replies and not retry_text:
                    try:
                        from wingman.content_policy import (
                            redact_transcript_block, redact_prose, REDACTION_NOTE,
                        )
                        print(f"[quick] Safe retry also blocked — final retry with redacted transcript...")
                        redacted_transcript = redact_transcript_block(transcript)

                        # Rebuild user_parts with the redacted transcript.
                        redacted_user_parts = []
                        if time_ctx:
                            redacted_user_parts.append(time_ctx)
                        redacted_user_parts.append(f"Conversation:\n{redacted_transcript}")
                        if goal:
                            redacted_user_parts.append(f"My goal for this chat: {redact_prose(goal)}")
                        if extra_ctx:
                            redacted_user_parts.append(f"Additional context: {redact_prose(extra_ctx)}")
                        redacted_user_parts.append(
                            "Format as JSON:\n"
                            "{\"read\": \"...\", \"advice\": \"...\", \"replies\": ["
                            "{\"label\": \"...\", \"text\": \"...\", \"why\": \"...\"}]}"
                        )
                        redacted_prompt = "\n\n".join(redacted_user_parts)
                        redacted_contents = [redacted_prompt]
                        # Intentionally DROP the screenshot on this tier —
                        # Pro's vision classifier can re-trigger the block.

                        redacted_system_parts = [safe_sys, REDACTION_NOTE]
                        if knowledge:
                            redacted_system_parts.append(knowledge)
                        if examples_block:
                            redacted_system_parts.append(examples_block)
                        if case_studies_block:
                            redacted_system_parts.append(case_studies_block)
                        redacted_config = gtypes.GenerateContentConfig(
                            system_instruction="\n\n".join(redacted_system_parts),
                            temperature=0.9,
                            max_output_tokens=max_tokens,
                            safety_settings=permissive_safety_settings(),
                        )
                        final_resp = await asyncio.to_thread(
                            client.models.generate_content,
                            model=model, contents=redacted_contents, config=redacted_config,
                        )
                        final_block = None
                        try:
                            final_block = getattr(final_resp.prompt_feedback, "block_reason", None)
                        except Exception:
                            pass
                        final_text = (final_resp.text or "").strip()
                        if final_text:
                            accumulated = final_text
                            result = ReplyGenerator._parse_response(accumulated)
                            if contact_name == wingman.current_contact:
                                await broadcast({"type": "reply_chunk", "text": accumulated, "contact": contact_name})
                            print(f"[quick] Redacted retry produced {len(result.replies)} replies")
                        else:
                            print(f"[quick] Redacted retry still blocked (block_reason={final_block}) — giving up for {contact_name}")
                    except Exception as exc:
                        print(f"[quick] Redacted retry failed: {exc}")

            if result.replies:
                reply_dicts = [o.to_dict() for o in result.replies]
                meta = wingman.store.load_meta(contact_name)
                meta["last_replies"] = reply_dicts
                meta["last_read"] = result.read
                meta["last_advice"] = result.advice
                meta["last_generated_at"] = _time.time()
                _lessons_applied = bool(case_studies_block)
                _examples_applied = bool(examples_block)
                meta["reply_history"] = [{
                    "replies": reply_dicts,
                    "read": result.read,
                    "advice": result.advice,
                    "mode": "lessons_on" if _lessons_applied else "lessons_off",
                    "lessons_applied": _lessons_applied,
                    "applied_case_studies": applied_case_studies,
                    "examples_applied": _examples_applied,
                    "applied_examples": applied_examples,
                }]
                meta["reply_history_index"] = 0
                wingman.store.save_meta(contact_name, meta)

                if contact_name == wingman.current_contact:
                    wingman.latest_replies = reply_dicts
                    wingman.latest_read = result.read
                    wingman.latest_advice = result.advice
                    wingman._reply_history = meta["reply_history"]
                    wingman._reply_history_index = 0
                    wingman.replies_version += 1
                    print(f"[quick] Replies live-updated for {contact_name}: {len(reply_dicts)} options")
                else:
                    wingman.unread_replies.add(contact_name)
                    print(f"[quick] Replies saved for {contact_name} (background): {len(reply_dicts)} options")

                # Completion notification. The quick-capture flow is
                # used by the global hotkey, which implies the user is
                # NOT currently watching Wingman — so fire a banner
                # regardless of which chat is foregrounded in the UI.
                # (Respect WINGMAN_NOTIFY=never to fully silence.)
                try:
                    import os as _os, urllib.parse as _ul
                    from wingman.notify import notify as _notify
                    if _os.getenv("WINGMAN_NOTIFY", "background") != "never":
                        body = reply_dicts[0].get("text", "")[:140] if reply_dicts else "Replies ready"
                        port = _os.getenv("WINGMAN_PORT", "8000")
                        deep = (
                            f"http://127.0.0.1:{port}/#contact={_ul.quote(contact_name, safe='')}"
                            if contact_name else ""
                        )
                        _notify(
                            title=contact_name or "Wingman",
                            body=body,
                            subtitle="Click to open",
                            open_url=deep,
                        )
                except Exception:
                    pass
            else:
                print(f"[quick] No replies parsed for {contact_name}")

        except Exception as exc:
            print(f"[quick] Isolated generation failed for {contact_name}: {exc}")

        wingman.status = "done"
        wingman._bump()

    # Fire-and-forget: each capture runs concurrently now instead of
    # queueing behind a serializing lock. On slow Pro days (like when
    # Google's Pro is 503-ing under load and every call takes 30s), the
    # old lock meant 5 hotkey presses stacked up for 2–3 minutes. Each
    # _process call is already per-capture-isolated — it has its own
    # frame_bytes, own local conversation, writes to its own chat file,
    # uses fresh clients via make_genai_client(). The shared state it
    # touches (saved_contacts, status) is mostly read-only or last-write-
    # wins UI state, not correctness-critical.
    asyncio.create_task(_process())
    return {"status": "queued", "contact": capture_contact}


@app.post("/api/rank-leads")
async def api_rank_leads():
    """Auto-analyze all chats and update lead rankings."""
    if not wingman:
        return {"error": "Not ready"}
    from wingman.lead_ranker import rank_all_leads
    playbook = wingman.training_rag.knowledge_summary if wingman.training_rag.status == "loaded" else ""
    rankings = await rank_all_leads(wingman.store, wingman.saved_contacts, playbook=playbook)
    for contact, rank in rankings.items():
        meta = wingman.store.load_meta(contact)
        meta["receptiveness"] = rank["score"]
        meta["lead_tag"] = rank["tag"]
        meta["lead_reason"] = rank["reason"]
        meta["lead_priority"] = rank["priority"]
        wingman.store.save_meta(contact, meta)
    wingman._bump()
    return {"ranked": len(rankings), "results": rankings}


@app.post("/api/rapid-fire/start")
async def rapid_fire_start(platform: str = Form("")):
    if not wingman:
        return {"error": "Not ready"}
    wingman.rapid_fire.start(platform)
    wingman._bump()
    return {"status": "recording", "platform": platform}


@app.post("/api/rapid-fire/stop")
async def rapid_fire_stop():
    """Stop recording and analyze the video with Flash."""
    if not wingman:
        return {"error": "Not ready"}
    wingman.rapid_fire.stop()
    wingman._bump()

    detected = await wingman.rapid_fire.analyze()
    results = wingman.rapid_fire.get_results()
    wingman._bump()
    return {"status": "analyzed", "detected": results}


@app.post("/api/rapid-fire/generate")
async def rapid_fire_generate(extra_context: str = Form("")):
    """Save all detected chats and generate replies for all in one batched call."""
    if not wingman:
        return {"error": "Not ready"}

    detected = wingman.rapid_fire.detected
    if not detected:
        return {"error": "No chats detected"}

    async def _process_all():
        from wingman.transcript import ConversationState
        import json as _json
        import time as _time

        contact_keys = []
        for chat in detected:
            contact = chat.get("contact", "Unknown")
            platform = chat.get("platform", "other")
            msgs = chat.get("messages", [])
            key = f"{platform} - {contact}" if wingman.rapid_fire._platform_hint else contact

            existing = wingman.store.load(key)
            conv = ConversationState()
            if existing:
                conv.ingest_parsed_messages(existing)
            if msgs:
                conv.ingest_parsed_messages(msgs)
            wingman.store.save(key, conv.messages)
            contact_keys.append(key)
            print(f"[rapid] Saved chat: {key} ({len(conv.messages)} msgs)")

        wingman.saved_contacts = wingman.store.list_contacts()
        wingman._bump()

        from wingman.config import REPLY_SYSTEM_PROMPT, PRO_MODEL, FLASH_MODEL
        from google.genai import types as gtypes

        use_flash = wingman.reply_model == "flash"
        model = FLASH_MODEL if use_flash else PRO_MODEL

        chat_blocks = []
        key_map = {}
        for key in contact_keys:
            msgs = wingman.store.load(key)
            last_15 = msgs[-15:] if len(msgs) > 15 else msgs
            msg_text = _json.dumps(last_15, ensure_ascii=False) if last_15 else "(no messages yet — give an opener)"
            chat_blocks.append(f"--- {key} ---\n{msg_text}")
            # Map both the full key and the contact name part to the stored key
            key_map[key] = key
            parts = key.split(" - ", 1)
            if len(parts) == 2:
                key_map[parts[1]] = key

        prompt = (
            "Generate reply options for EACH of these conversations.\n\n"
            "Return a JSON object keyed by the EXACT contact label shown above (including platform prefix if present):\n\n"
            "For each conversation:\n"
            "- If there are messages: give a read, advice, and 3-5 reply options\n"
            "- If there are NO messages (just matched, no conversation yet): "
            "the 'read' should say 'New match — no conversation yet', "
            "the 'advice' should be about opening strategy, and "
            "give 3-5 DIFFERENT opener options as the replies. "
            "Openers should be creative, short, fun, and NOT generic. "
            "Use the coaching style to craft openers that hook.\n\n"
            "Format:\n"
            "{\"exact label\": {\"read\": \"...\", \"advice\": \"...\", "
            "\"replies\": [{\"label\": \"...\", \"text\": \"...\", \"why\": \"...\"}]}}\n\n"
            "Be specific. Reply texts should be short like real texts with emojis where natural.\n\n"
            + "\n\n".join(chat_blocks)
        )

        _rapid_custom_sys = ""
        try:
            _rapid_custom_sys = (wingman.global_settings.custom_reply_system_prompt or "").strip()
        except Exception:
            _rapid_custom_sys = ""
        _rapid_base = _rapid_custom_sys or REPLY_SYSTEM_PROMPT
        system_parts = [_rapid_base.split("Conversation:\n{transcript}")[0].rstrip()]
        if wingman.use_training and wingman.training_rag.status == "loaded":
            system_parts.append(wingman.training_rag.knowledge_summary)

        wingman.status = "generating"
        wingman._bump()
        print(f"[rapid] Generating replies for {len(contact_keys)} chats...")

        try:
            client = wingman.generator._get_client()
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=prompt,
                config=gtypes.GenerateContentConfig(
                    system_instruction="\n\n".join(system_parts),
                    temperature=0.9,
                    max_output_tokens=16384,
                ),
            )

            import re
            text = response.text.strip()
            fence = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
            if fence:
                text = fence.group(1).strip()
            data = _json.loads(text)

            if isinstance(data, dict):
                for model_key, result in data.items():
                    if not isinstance(result, dict):
                        continue
                    stored_key = key_map.get(model_key, model_key)
                    replies = result.get("replies", [])
                    meta = wingman.store.load_meta(stored_key)
                    meta["last_replies"] = replies
                    meta["last_read"] = result.get("read", "")
                    meta["last_advice"] = result.get("advice", "")
                    meta["last_generated_at"] = _time.time()
                    meta["reply_history"] = [{"replies": replies, "read": meta["last_read"], "advice": meta["last_advice"]}]
                    meta["reply_history_index"] = 0
                    wingman.store.save_meta(stored_key, meta)
                    wingman.unread_replies.add(stored_key)
                    print(f"[rapid] Replies saved for {stored_key}: {len(replies)} options")

            wingman.status = "done"
            wingman._bump()
            print("[rapid] All replies generated")

        except Exception as exc:
            print(f"[rapid] Batch generation failed: {exc}")
            wingman.status = "idle"
            wingman._bump()

    asyncio.create_task(_process_all())
    return {"status": "generating", "chats": [c.get("contact", "") for c in detected]}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        if wingman:
            await ws.send_text(json.dumps({"type": "status", **_state()}))
            if wingman.conversation.messages:
                await ws.send_text(json.dumps({"type": "transcript", "messages": wingman.conversation.to_display_list()}))
            if wingman.latest_replies:
                await ws.send_text(json.dumps({
                    "type": "replies",
                    "replies_version": wingman.replies_version,
                    "options": wingman.latest_replies,
                    "read": wingman.latest_read,
                    "advice": wingman.latest_advice,
                }))
    except Exception:
        pass

    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
            except Exception:
                continue
            action = msg.get("action")

            if action == "new_chat":
                wingman.conversation.messages.clear()
                wingman.latest_replies = []
                wingman.latest_read = ""
                wingman.latest_advice = ""
                wingman.current_contact = ""
                wingman.collecting_count = 0
                wingman.active_preset = wingman.default_preset
                wingman.transcript_version += 1
                wingman.replies_version += 1
                wingman.status = "idle"
                wingman._bump()
                print("[server] New chat started")
            elif action == "start_reading":
                contact = msg.get("contact", "")
                context = msg.get("context", "")
                wingman.start_collecting(contact, context)
            elif action == "stop_reading":
                asyncio.create_task(wingman.stop_collecting())
            elif action == "regenerate":
                wingman._pending_regen = msg.get("preset", -1)
                wingman._regen_extra_context = msg.get("extra_context", "")
            elif action == "set_reply_model":
                m = msg.get("model", "pro")
                wingman.reply_model = m if m in ("pro", "flash", "tuned") else "pro"
                wingman._bump()
                print(f"[server] Reply model set to: {wingman.reply_model}")
            elif action == "set_tuned_version":
                v = (msg.get("version") or "").strip().lower()
                if v in ("v1", "v2", "v3", "v4"):
                    from wingman.tuned_flash_client import set_active_version
                    set_active_version(v)
                    wingman._bump()
                    print(f"[server] Tuned model version: {v}")
            elif action == "set_use_training":
                wingman.use_training = bool(msg.get("enabled", False))
                wingman._bump()
                print(f"[server] Training context: {'on' if wingman.use_training else 'off'}")
            elif action == "set_use_kie":
                wingman.use_kie = bool(msg.get("enabled", False))
                wingman._bump()
                print(f"[server] KIE proxy: {'ON — routing Pro through KIE' if wingman.use_kie else 'off (Google direct)'}")
            elif action == "set_use_grok":
                wingman.use_grok = bool(msg.get("enabled", False))
                wingman._bump()
                print(f"[server] Grok: {'ON — routing Pro through xAI ('+wingman.grok_mode+')' if wingman.use_grok else 'off (Google direct)'}")
            elif action == "set_grok_mode":
                m = (msg.get("mode") or "multi-agent").strip().lower()
                if m in ("multi-agent", "reasoning", "non-reasoning"):
                    wingman.grok_mode = m
                    wingman._bump()
                    print(f"[server] Grok mode: {m}")
            elif action == "set_grok_full_training":
                wingman.grok_full_training = bool(msg.get("enabled", False))
                wingman._bump()
                if wingman.grok_full_training:
                    # Load lazily if it wasn't at startup
                    if not wingman.training_corpus._loaded:
                        wingman.training_corpus.load()
                    print(f"[server] Grok full training: ON "
                          f"({wingman.training_corpus.file_count} files, "
                          f"{wingman.training_corpus.char_count:,} chars)")
                else:
                    print("[server] Grok full training: OFF")
            elif action == "set_use_deepseek":
                wingman.use_deepseek = bool(msg.get("enabled", False))
                wingman._bump()
                print(f"[server] DeepSeek V4 Pro: "
                      f"{'ON — routing Pro through DeepSeek' if wingman.use_deepseek else 'off (Google direct)'}")
            elif action == "set_deepseek_mode":
                m = (msg.get("mode") or "normal").strip().lower()
                if m in ("normal", "full"):
                    wingman.deepseek_mode = m
                    wingman._bump()
                    if m == "full" and not wingman.training_corpus._loaded:
                        wingman.training_corpus.load()
                    print(f"[server] DeepSeek mode: {m}")
            elif action == "set_deepseek_variant":
                v = (msg.get("variant") or "pro").strip().lower()
                if v in ("pro", "flash"):
                    wingman.deepseek_variant = v
                    wingman._bump()
                    print(f"[server] DeepSeek variant: {v}")
            elif action == "set_use_lessons":
                wingman.use_lessons = bool(msg.get("enabled", True))
                wingman._bump()
                print(f"[server] Case-study lessons: {'ON' if wingman.use_lessons else 'off'}")
            elif action == "set_use_examples":
                wingman.use_examples = bool(msg.get("enabled", True))
                wingman._bump()
                print(f"[server] Good-reply examples: {'ON' if wingman.use_examples else 'off'}")
            elif action == "rebuild_examples_library":
                wingman.rebuild_examples_library()
            elif action == "flag_bad_outcome":
                c = msg.get("contact", "") or wingman.current_contact
                note = (msg.get("note") or "").strip()
                if c:
                    wingman.flag_bad_outcome(c, note=note)
            elif action == "unflag_bad_outcome":
                c = msg.get("contact", "") or wingman.current_contact
                if c:
                    wingman.unflag_bad_outcome(c)
            elif action == "rebuild_case_study":
                c = msg.get("contact", "") or wingman.current_contact
                if c:
                    # Explicit rebuild — useful after meaningful new
                    # messages get added to an already-flagged chat.
                    asyncio.create_task(wingman._build_case_study_for(c))
            elif action == "clear_unread":
                c = msg.get("contact", wingman.current_contact)
                if c:
                    wingman.clear_unread(c)
            elif action == "set_reply_history_index":
                idx = int(msg.get("index", 0))
                wingman.set_reply_history_index(idx)
            elif action == "set_receptiveness":
                contact = msg.get("contact", wingman.current_contact)
                val = max(0, min(10, int(msg.get("value", 5))))
                if contact:
                    meta = wingman.store.load_meta(contact)
                    meta["receptiveness"] = val
                    wingman.store.save_meta(contact, meta)
                    wingman._bump()
                    print(f"[server] Receptiveness for {contact}: {val}/10")
            elif action == "set_locked_extra_context":
                # Sticky per-chat extra context. Empty string = unlock.
                contact = msg.get("contact", wingman.current_contact)
                value = (msg.get("value") or "").strip()
                if contact:
                    meta = wingman.store.load_meta(contact)
                    if value:
                        meta["locked_extra_context"] = value
                    else:
                        meta.pop("locked_extra_context", None)
                    wingman.store.save_meta(contact, meta)
                    wingman._bump()
                    print(f"[server] Locked extra context for {contact}: "
                          f"{'(cleared)' if not value else value[:60]+'...'}")
            elif action == "set_global_extra_context":
                # Sticky global extra context — applies to EVERY chat
                # (existing + new). Empty string = unlock.
                value = (msg.get("value") or "").strip()
                wingman.global_settings.set_global_extra_context(value)
                wingman._bump()
                print(f"[server] Global extra context: "
                      f"{'(cleared)' if not value else value[:60]+'...'}")
            elif action == "set_custom_reply_system_prompt":
                # User-edited baseline prompt (the "No goal" default).
                # Empty string = clear/reset to the factory
                # REPLY_SYSTEM_PROMPT from wingman/config.py.
                value = (msg.get("value") or "").strip()
                wingman.global_settings.set_custom_reply_system_prompt(value)
                wingman._bump()
                if value:
                    print(f"[server] Custom reply system prompt set ({len(value)} chars)")
                else:
                    print("[server] Custom reply system prompt CLEARED — using factory default")
            elif action == "reset_reply_system_prompt":
                # One-click safety button: restore the factory default
                # by clearing the override. Separate action from
                # set_*=\"\" so the client can express intent cleanly.
                wingman.global_settings.set_custom_reply_system_prompt("")
                wingman._bump()
                print("[server] Reply system prompt reset to factory default")
            elif action == "set_preset":
                wingman.active_preset = msg.get("index", -1)
                if wingman.current_contact:
                    meta = wingman.store.load_meta(wingman.current_contact)
                    meta["active_preset"] = wingman.active_preset
                    wingman.store.save_meta(wingman.current_contact, meta)
                wingman._bump()
            elif action == "set_default_preset":
                wingman.default_preset = msg.get("index", -1)
                wingman._bump()
                print(f"[server] Default preset set to: {wingman.default_preset}")
            elif action == "add_preset":
                wingman.presets.add(msg.get("name", ""), msg.get("instruction", ""))
                wingman._bump()
            elif action == "delete_preset":
                wingman.presets.delete(msg.get("index", -1))
                if wingman.active_preset == msg.get("index", -1):
                    wingman.active_preset = -1
                wingman._bump()
            elif action == "edit_message":
                idx = msg.get("index", -1)
                msgs = wingman.conversation.messages
                if 0 <= idx < len(msgs):
                    if "speaker" in msg:
                        msgs[idx].speaker = msg["speaker"]
                    if "text" in msg:
                        msgs[idx].text = msg["text"]
                    if msg.get("delete"):
                        msgs.pop(idx)
                    wingman.transcript_version += 1
                    if wingman.current_contact:
                        wingman.store.save(wingman.current_contact, msgs)
                    wingman._bump()
            elif action == "load_contact":
                wingman.load_contact(msg.get("contact", ""))
            elif action == "rename_contact":
                old_name = msg.get("old_name", "")
                new_name = msg.get("new_name", "")
                if old_name and new_name and old_name != new_name:
                    old_msgs = wingman.store.load(old_name)
                    if old_msgs:
                        old_meta = wingman.store.load_meta(old_name)
                        wingman.store.delete(old_name)
                        wingman.store.save_raw(new_name, old_msgs)
                        if old_meta:
                            wingman.store.save_meta(new_name, old_meta)
                        try:
                            wingman.case_studies.rename(old_name, new_name)
                        except Exception:
                            pass
                        wingman.saved_contacts = wingman.store.list_contacts()
                        if wingman.current_contact == old_name:
                            wingman.current_contact = new_name
                        wingman.transcript_version += 1
                        wingman._bump()
                        print(f"[server] Renamed chat: {old_name} -> {new_name}")
            elif action == "delete_contact":
                contact = msg.get("contact", "")
                if contact:
                    wingman.store.delete(contact)
                    try:
                        wingman.case_studies.delete(contact)
                    except Exception:
                        pass
                    wingman.saved_contacts = wingman.store.list_contacts()
                    if wingman.current_contact == contact:
                        wingman.conversation.messages.clear()
                        wingman.latest_replies = []
                        wingman.latest_read = ""
                        wingman.latest_advice = ""
                        wingman.current_contact = ""
                        wingman.transcript_version += 1
                        wingman.replies_version += 1
                        wingman.status = "idle"
                    wingman._bump()
                    print(f"[server] Deleted chat: {contact}")
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def run_server():
    import uvicorn
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)

if __name__ == "__main__":
    run_server()
