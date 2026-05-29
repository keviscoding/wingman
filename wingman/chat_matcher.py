"""Local fuzzy chat matcher — ported from desktop's ``server/app.py``.

The desktop hotkey path solved same-name chat disambiguation completely
years ago using a structured local fuzzy matcher (``thefuzz`` /
Levenshtein) plus distinctiveness gates plus a 3-tier decision system.
The mobile/SaaS pipeline shipped without this brain and has been
relying on the Flash Lite adjudicator for all decisions — which keeps
getting fooled by shared casual tone, identical platform UI banners,
and same-first-name coincidences.

This module is the desktop logic, lifted out and made framework-free
so the SaaS pipeline can call it directly. Most functions are pure
ports; minor mobile-specific tweaks are called out below.

Mobile tweaks vs the desktop original:

  • ``base_name_lower`` accepts BOTH ``" N"`` and ``"(N)"`` suffix
    forms. Mobile shipped with " N" (space-separator) earlier so we
    keep accepting that for collision detection. New disambiguations
    we generate use ``" N"`` for backwards-compat with existing rows.
  • ``disambiguate_name`` takes the full chat list (with messages
    already loaded) instead of a separate `store` callable. Cheaper —
    the SaaS dispatcher already has it in scope.
  • ``match_by_transcript_overlap`` and ``gather_candidates`` accept
    the same chat list shape ``[{"contact": str, "messages": [...]}, ...]``
    instead of a contacts-list-plus-store-loader pair. Same logic.

Public API (snake_case, no leading underscores):

  • ``MATCH_THRESHOLD`` / ``MATCH_MARGIN`` / ``SCREENSHOT_TAIL`` /
    ``SAVED_TAIL`` / ``ALIGN_MSG_RATIO`` / ``CHARS_DISTINCTIVE`` /
    ``CHARS_MODERATE`` / ``STRONG_SCORE`` / ``STRONG_MIN_K``
  • ``norm_text(t) -> str``
  • ``msg_texts(messages, tail) -> list[str]``
  • ``alignment_run(screen, saved, fz) -> (k, ends_at_tail, chars)``
  • ``score_contact(screen_texts, saved_texts, fz) -> int``
  • ``match_by_transcript_overlap(extracted_msgs, all_chats) -> (contact, score)``
  • ``is_strong_local_match(screen_texts, saved_texts, fz, score) -> bool``
  • ``base_name_lower(name) -> str``
  • ``name_collides(proposed, saved_names) -> bool``
  • ``disambiguate_name(proposed, all_chats) -> str``
  • ``gather_candidates(proposed, tx_match, tx_score, all_chats, max_candidates=3) -> list[(contact, msgs)]``
"""

from __future__ import annotations

import re
import unicodedata


# ─────────────── Tunables ───────────────
MATCH_THRESHOLD = 50      # absolute score needed to merge (0-100)
MATCH_MARGIN = 8          # best must beat second-best by this much
SCREENSHOT_TAIL = 10      # how many recent screenshot messages to compare
SAVED_TAIL = 30           # how many recent saved messages to compare
ALIGN_MSG_RATIO = 80      # per-message fuzzy threshold for alignment
CHARS_DISTINCTIVE = 60    # alignment chars = strong evidence
CHARS_MODERATE = 30       # alignment chars = medium evidence
STRONG_SCORE = 70         # Tier 1 fast-merge composite-score floor
STRONG_MIN_K = 3          # Tier 1 minimum aligned messages


# ─────────────── Text normalization ───────────────

# Strip unicode emoji / pictographs / symbols. Equal across platforms
# regardless of Flash returning 😉 while storage has ;) or vice versa.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FFFF"  # supplementary planes
    "\U00002600-\U000027BF"  # misc symbols + dingbats
    "\U0000FE0F"             # variation selector 16
    "\U0000200D"             # zero-width joiner
    "]+",
    flags=re.UNICODE,
)
# Trailing/leading punctuation that drifts across captures
# ("hey.." vs "hey", "Okay!" vs "Okay"). We keep interior chars so
# "you're" stays distinguishable from "you".
_PUNCT_RE = re.compile(r"[^\w\s']", flags=re.UNICODE)


def norm_text(t: str) -> str:
    """Normalize a message for comparison only (never for storage):

      • NFKC-fold (fullwidth → regular, compatibility forms, etc.)
      • lowercase
      • strip emoji/symbol variants
      • strip punctuation other than word chars / whitespace / apostrophes
      • collapse whitespace

    So ``"Good girl. Save it as Kevis ;)"`` and
    ``"Good girl, Save it as Kevis 😉"`` both fold to
    ``"good girl save it as kevis"`` and fuzzy-match 100.
    """
    if not t:
        return ""
    t = unicodedata.normalize("NFKC", t).lower()
    t = _EMOJI_RE.sub(" ", t)
    t = _PUNCT_RE.sub(" ", t)
    return " ".join(t.split())


def msg_texts(messages: list[dict], tail: int) -> list[str]:
    """Last ``tail`` normalized message texts, dropping empties and
    media placeholders like ``"[image]"``. Order preserved
    (oldest → newest)."""
    out: list[str] = []
    for m in (messages or [])[-tail:]:
        raw = (m.get("text") or "").strip()
        # Detect media placeholders BEFORE normalization, since _PUNCT_RE
        # would strip the brackets.
        if raw.startswith("[") and raw.endswith("]"):
            continue
        t = norm_text(raw)
        if not t:
            continue
        out.append(t)
    return out


# ─────────────── Alignment + scoring ───────────────

def alignment_run(
    screenshot: list[str], saved: list[str], fz,
) -> tuple[int, bool, int]:
    """Longest contiguous run of fuzzy-matching consecutive messages.
    Tries up to the first 2 screenshot positions as starting anchors —
    Flash sometimes hallucinates a header/title as the top "message"
    and we want to align past that.

    Returns ``(run_length, ends_at_saved_tail, total_aligned_chars)``.

    The char count is used by the scorer to distinguish distinctive
    content runs from generic openers — a run of 3 long messages
    counts very differently from a run of 3 ``"hey"``s.
    """
    if not screenshot or not saved:
        return 0, False, 0
    saved_len = len(saved)
    screen_len = len(screenshot)

    best_run = 0
    best_ends_at_tail = False
    best_chars = 0

    max_start = min(2, screen_len)
    for start_i in range(max_start):
        s_anchor = screenshot[start_i]
        for j in range(saved_len):
            if fz.ratio(s_anchor, saved[j]) < ALIGN_MSG_RATIO:
                continue
            run = 1
            chars = len(screenshot[start_i])
            while (start_i + run) < screen_len and (j + run) < saved_len:
                if fz.ratio(screenshot[start_i + run], saved[j + run]) < ALIGN_MSG_RATIO:
                    break
                chars += len(screenshot[start_i + run])
                run += 1
            ends_at_tail = (j + run) == saved_len
            if run > best_run or (run == best_run and ends_at_tail and not best_ends_at_tail):
                best_run = run
                best_ends_at_tail = ends_at_tail
                best_chars = chars
                if best_run >= 5 and best_ends_at_tail:
                    return best_run, best_ends_at_tail, best_chars

    return best_run, best_ends_at_tail, best_chars


def score_contact(
    screenshot_texts: list[str],
    saved_texts: list[str],
    fz,
) -> int:
    """Composite similarity 0-100 between a screenshot and one saved
    chat. Four signals, ordered by decisiveness:

      1. Alignment run (0-55) — consecutive messages in order.
         Distinctiveness gate: a short run of generic openers earns
         far less than a short run of substantive content. Tail-anchored
         alignments get extra weight as they imply a clean continuation.
      2. Tail partial_ratio (0-30) — overall fuzzy content overlap,
         dampened when alignment was short AND not distinctive AND
         coverage is low.
      3. Last-message bonus (0-20) — exact or near-exact tail match.
      4. Verbatim count (0-15) — how many screenshot messages appear
         verbatim anywhere in saved.
    """
    if not screenshot_texts or not saved_texts:
        return 0

    screen_len = len(screenshot_texts)
    saved_len = len(saved_texts)

    # 1. Alignment.
    k, ends_at_tail, chars = alignment_run(screenshot_texts, saved_texts, fz)

    if k == 0:
        align_bonus = 0
    elif ends_at_tail:
        if chars >= CHARS_DISTINCTIVE or k >= 3:
            align_bonus = 55
        elif chars >= CHARS_MODERATE or k >= 2:
            align_bonus = 40
        else:
            align_bonus = 18  # k=1 tail anchor only
    else:
        if chars >= CHARS_DISTINCTIVE:
            align_bonus = 55 if k >= 3 else 45
        elif chars >= CHARS_MODERATE and k >= 2:
            align_bonus = 32
        else:
            align_bonus = 0

    # 2. Tail partial_ratio.
    sig_s = " | ".join(screenshot_texts)
    sig_v = " | ".join(saved_texts)
    partial = fz.partial_ratio(sig_s, sig_v)
    coverage = screen_len / max(saved_len, 1)
    if (not ends_at_tail
            and chars < CHARS_MODERATE
            and coverage < 0.5):
        partial *= 0.3
    partial_score = partial * 0.3  # 0-30

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


def match_by_transcript_overlap(
    extracted_messages: list[dict],
    all_chats: list[dict],
) -> tuple[str, int]:
    """Score the screenshot against every saved chat and return
    ``(best_contact, best_score)`` if the winner beats both
    ``MATCH_THRESHOLD`` and the runner-up by ``MATCH_MARGIN``.

    The margin rule protects against picking the wrong Amy when two
    similar chats look vaguely right — we'd rather route to a fresh
    disambiguated chat than silently merge into the wrong one.

    ``all_chats`` is a list of dicts with at least ``"contact"`` and
    ``"messages"`` keys (matches what ``db.chat_list`` returns).
    """
    screenshot_texts = msg_texts(extracted_messages, SCREENSHOT_TAIL)
    if len(screenshot_texts) < 2 or not all_chats:
        return "", 0
    try:
        from thefuzz import fuzz as _fz
    except Exception:
        # No fuzzy lib available — caller falls back to text adjudicator.
        return "", 0

    best_contact = ""
    best_score = 0
    second_score = 0

    for chat in all_chats:
        contact = chat.get("contact") or ""
        if not contact:
            continue
        stored = chat.get("messages") or []
        if not stored:
            continue
        saved_texts = msg_texts(stored, SAVED_TAIL)
        if not saved_texts:
            continue

        s = score_contact(screenshot_texts, saved_texts, _fz)

        if s > best_score:
            second_score = best_score
            best_score = s
            best_contact = contact
            if best_score >= 95:
                break
        elif s > second_score:
            second_score = s

    if best_score < MATCH_THRESHOLD:
        return "", best_score
    if (best_score - second_score) < MATCH_MARGIN:
        # Ambiguity — refuse silent merge.
        return "", best_score
    return best_contact, best_score


def is_strong_local_match(
    screenshot_texts: list[str],
    saved_texts: list[str],
    fz,
    score: int,
) -> bool:
    """Tier 1 gate. A 'strong' local match lets us skip the Flash
    adjudicator entirely. All four conditions must hold:

      • composite score ≥ STRONG_SCORE
      • alignment k ≥ STRONG_MIN_K (3+ consecutive aligned messages)
      • tail-anchored (true continuation, not mid-thread)
      • aligned content ≥ CHARS_DISTINCTIVE (real text, not "hey"s)
    """
    if score < STRONG_SCORE:
        return False
    k, ends_at_tail, chars = alignment_run(screenshot_texts, saved_texts, fz)
    return k >= STRONG_MIN_K and ends_at_tail and chars >= CHARS_DISTINCTIVE


# ─────────────── Same-name handling ───────────────

# Strip BOTH " N" (mobile-shipped convention) AND "(N)" (desktop
# convention) suffixes when computing base names. Mobile chats from
# before the unified scheme are " N"; new disambiguations on mobile
# also use " N" for backwards-compat with that data. Desktop emits
# "(N)" — accepting both means a mixed-history database collides
# correctly across both forms.
_SUFFIX_RE = re.compile(r"\s*(?:\(\d+\)|\s+\d+)\s*$")


def base_name_lower(name: str) -> str:
    """Strip a trailing ``" N"`` or ``"(N)"`` disambiguator and
    lowercase. Used to group chats that belong to the same first-name
    surface.

    ``"Amy"`` → ``"amy"``
    ``"Amy 2"`` → ``"amy"``
    ``"Amy (3)"`` → ``"amy"``
    ``"whatsapp - Cyn (4)"`` → ``"whatsapp - cyn"``
    """
    s = (name or "").strip()
    if not s:
        return ""
    return _SUFFIX_RE.sub("", s).strip().lower()


def name_collides(proposed: str, saved_names: list[str]) -> bool:
    """Does any saved chat share the same base name as ``proposed``?
    Case-insensitive, ignores " N"/"(N)" disambiguator suffixes."""
    if not proposed or not saved_names:
        return False
    base = base_name_lower(proposed)
    if not base:
        return False
    return any(base_name_lower(s) == base for s in saved_names)


def disambiguate_name(proposed: str, all_chats: list[dict]) -> str:
    """Return a fresh contact name for a newly-decided chat, never
    silently merging into an existing populated row.

    Preference order:

      1. If ``proposed`` doesn't exist yet anywhere → use it.
      2. If ``proposed`` exists but the on-disk row is EMPTY (a
         placeholder from a failed earlier capture) → reuse it.
         Prevents the "parade of ghost chats" pollution.
      3. Otherwise try ``"proposed 2"``, ``"proposed 3"``… reusing
         empty slots, finally returning the first totally-free slot.
      4. Never reuse a non-empty existing row of the same name —
         that would silently merge two different people.

    ``all_chats`` is the already-loaded chat list with messages, so
    the empty-row check is in-memory and free.
    """
    if not proposed:
        return proposed
    by_lower: dict[str, dict] = {}
    for c in (all_chats or []):
        contact = (c.get("contact") or "").strip()
        if not contact:
            continue
        # Last write wins if there's a duplicate (rare; should not
        # happen because chat_id is unique).
        by_lower[contact.lower()] = c

    def _is_empty(chat: dict) -> bool:
        msgs = chat.get("messages") or []
        return not msgs

    for n in range(1, 200):
        # Mobile uses " N" suffix (matches existing data). For the
        # base case (n=1) this is just the proposed name.
        cand = proposed if n == 1 else f"{proposed} {n}"
        existing = by_lower.get(cand.lower())
        if existing is None:
            return cand  # brand-new slot
        if _is_empty(existing):
            return existing.get("contact") or cand  # reuse empty placeholder
    # Worst case fallback — never hit in practice.
    return f"{proposed} {len(all_chats) + 1}"


def gather_candidates(
    proposed: str,
    local_best: str,
    local_best_score: int,
    all_chats: list[dict],
    max_candidates: int = 3,
) -> list[tuple[str, list[dict]]]:
    """Build the candidate list passed to the Flash Lite adjudicator.

    Includes:
      • Up to ``max_candidates`` saved chats whose base name matches
        ``proposed`` (covers ``"Jess"``, ``"Jess 2"``, ``"Jess (3)"``).
      • Plus the local matcher's top result if it's a different
        contact and scored ≥ 30 (might be the same person stored
        under a renamed key, e.g. moved-to-WhatsApp).

    Each candidate ships with its last ``SAVED_TAIL`` messages.
    Empty chats are excluded — nothing to compare.
    """
    base = base_name_lower(proposed)
    collected: list[tuple[str, list[dict]]] = []
    seen: set[str] = set()

    # Pass 1: same-base-name chats.
    for chat in (all_chats or []):
        contact = chat.get("contact") or ""
        if not contact:
            continue
        if base_name_lower(contact) != base:
            continue
        if contact in seen:
            continue
        msgs = chat.get("messages") or []
        if not msgs:
            continue
        collected.append((contact, msgs[-SAVED_TAIL:]))
        seen.add(contact)
        if len(collected) >= max_candidates:
            break

    # Pass 2: local matcher's top result if outside the name group
    # but plausibly the same person.
    if (
        local_best
        and local_best not in seen
        and local_best_score >= 30
        and len(collected) < max_candidates
    ):
        for chat in (all_chats or []):
            if (chat.get("contact") or "") != local_best:
                continue
            msgs = chat.get("messages") or []
            if msgs:
                collected.append((local_best, msgs[-SAVED_TAIL:]))
                seen.add(local_best)
            break

    return collected
