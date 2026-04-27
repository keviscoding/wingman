"""User store. Dual-backend: Postgres in prod, SQLite for local dev.

When ``DATABASE_URL`` env var is set (DigitalOcean / Railway / wherever
managed Postgres is wired in), all queries go through psycopg. When
it's unset (local laptop, tests, the desktop server), we fall back to
the stdlib SQLite at ``data/saas/wingman.sqlite3``.

The two backends share a SQL surface that's nearly identical — the
only meaningful gap is parameter placeholders (``?`` vs ``%s``), which
the helper below rewrites at query time. Schema is written in Postgres
syntax and the SQLite path translates ``BIGSERIAL`` etc. on init.

Tables:
  users        — accounts (plan, push_token, quotas)
  sessions     — JWT revocation
  generations  — audit trail of every reply call
  jobs         — async generation queue (mobile polls / receives push)
  chats        — per-user chats (NEW; replaces filesystem JSON storage
                 so chats survive container redeploys and scale
                 horizontally)
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


# ─────────────── Backend selection ───────────────

_PG_URL = (os.getenv("DATABASE_URL") or "").strip()
USE_PG = _PG_URL.startswith("postgres://") or _PG_URL.startswith("postgresql://")

# Local SQLite fallback path (only used when USE_PG is False)
DB_PATH = Path(os.getenv("WINGMAN_SAAS_DB", "data/saas/wingman.sqlite3"))


def _ensure_dir() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# psycopg is only imported when needed so SQLite-only environments
# (the desktop server, tests) don't have to install it.
def _pg_connect():
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(
        _PG_URL,
        row_factory=dict_row,
        autocommit=False,
    )


class _DictRow(dict):
    """Wrap a dict so callers can use ``row[i]`` semantics from SQLite or
    ``row["col"]`` semantics from Postgres interchangeably."""

    def __getitem__(self, key):
        return super().__getitem__(key)

    def keys(self):
        return super().keys()


class _Cursor:
    """Thin wrapper around either sqlite3.Cursor or psycopg.Cursor that
    rewrites ``?`` placeholders to ``%s`` for Postgres, and returns
    dict-shaped rows from both."""

    def __init__(self, raw_cursor, is_pg: bool):
        self._c = raw_cursor
        self._is_pg = is_pg

    def execute(self, sql: str, params: tuple | list = ()):
        if self._is_pg:
            sql = sql.replace("?", "%s")
        self._c.execute(sql, params)
        return self

    def fetchone(self):
        row = self._c.fetchone()
        if row is None:
            return None
        if self._is_pg:
            return _DictRow(row)
        # sqlite3.Row supports both index and key access; copy to dict
        return _DictRow({k: row[k] for k in row.keys()})

    def fetchall(self):
        rows = self._c.fetchall()
        if self._is_pg:
            return [_DictRow(r) for r in rows]
        return [_DictRow({k: r[k] for k in r.keys()}) for r in rows]


class _Connection:
    """Wraps either sqlite3.Connection or psycopg.Connection so callers
    have one shape. Used as a context manager (commits on success,
    rolls back on error)."""

    def __init__(self, raw, is_pg: bool):
        self._raw = raw
        self._is_pg = is_pg

    def execute(self, sql: str, params: tuple | list = ()):
        if self._is_pg:
            sql = sql.replace("?", "%s")
            cur = self._raw.cursor()
            cur.execute(sql, params)
            return _Cursor(cur, True)
        cur = self._raw.execute(sql, params)
        return _Cursor(cur, False)

    def executescript(self, script: str):
        if self._is_pg:
            # psycopg has no executescript; split on semicolons after
            # stripping comments/blank lines. Postgres-compatible DDL.
            for stmt in _split_sql(script):
                if stmt:
                    self._raw.cursor().execute(stmt)
        else:
            self._raw.executescript(script)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()


def _split_sql(script: str) -> list[str]:
    """Naive multi-statement splitter — strips line comments and splits
    on `;`. Good enough for our schema (no string literals contain ';')."""
    out, buf = [], []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            out.append("\n".join(buf).rstrip(";").strip())
            buf = []
    if buf:
        tail = "\n".join(buf).strip()
        if tail:
            out.append(tail.rstrip(";"))
    return [s for s in out if s.strip()]


@contextmanager
def connect() -> Iterator[_Connection]:
    """Per-call connection. Commits on clean exit, rolls back on error.
    Postgres uses real connection pooling under the hood at psycopg's
    layer; SQLite is fine without a pool at our scale."""
    if USE_PG:
        raw = _pg_connect()
        wrapped = _Connection(raw, is_pg=True)
    else:
        _ensure_dir()
        raw = sqlite3.connect(str(DB_PATH), timeout=30.0)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA journal_mode=WAL")
        raw.execute("PRAGMA foreign_keys=ON")
        wrapped = _Connection(raw, is_pg=False)
    try:
        yield wrapped
        wrapped.commit()
    except Exception:
        try:
            wrapped.rollback()
        except Exception:
            pass
        raise
    finally:
        wrapped.close()


# ─────────────── Schema ───────────────
#
# Postgres-flavored DDL. The few SQLite-isms (AUTOINCREMENT, PRAGMA)
# we need are translated at init time. ``BIGINT`` is used everywhere
# we'd otherwise want INT — both backends accept it.

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS users (
  id                   TEXT PRIMARY KEY,
  email                TEXT NOT NULL UNIQUE,
  password_hash        TEXT NOT NULL,
  display_name         TEXT,
  plan                 TEXT NOT NULL DEFAULT 'free',
  lifetime_gens_used   BIGINT NOT NULL DEFAULT 0,
  daily_count          BIGINT NOT NULL DEFAULT 0,
  pro_lifetime_used    BIGINT NOT NULL DEFAULT 0,
  pro_daily_count      BIGINT NOT NULL DEFAULT 0,
  daily_window_start   BIGINT NOT NULL DEFAULT 0,
  created_at           BIGINT NOT NULL,
  subscription_until   BIGINT,
  push_token           TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
  jti           TEXT PRIMARY KEY,
  user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  issued_at     BIGINT NOT NULL,
  expires_at    BIGINT NOT NULL,
  revoked       BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);

CREATE TABLE IF NOT EXISTS generations (
  id            BIGSERIAL PRIMARY KEY,
  user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  ts            BIGINT NOT NULL,
  model         TEXT NOT NULL,
  cost_cents    DOUBLE PRECISION NOT NULL DEFAULT 0,
  reply_count   BIGINT NOT NULL DEFAULT 5
);
CREATE INDEX IF NOT EXISTS generations_user_idx ON generations(user_id, ts);

CREATE TABLE IF NOT EXISTS jobs (
  id            TEXT PRIMARY KEY,
  user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status        TEXT NOT NULL,
  mode          TEXT NOT NULL,
  contact       TEXT,
  chat_id       TEXT,
  result_json   TEXT,
  error_detail  TEXT,
  created_at    BIGINT NOT NULL,
  updated_at    BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_user_idx ON jobs(user_id, created_at);

CREATE TABLE IF NOT EXISTS chats (
  id                TEXT PRIMARY KEY,
  user_id           TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  contact           TEXT NOT NULL,
  messages_json     TEXT NOT NULL DEFAULT '[]',
  meta_json         TEXT NOT NULL DEFAULT '{}',
  last_activity_at  DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS chats_user_idx ON chats(user_id, last_activity_at);
CREATE UNIQUE INDEX IF NOT EXISTS chats_user_contact_idx ON chats(user_id, contact);
"""

# SQLite version uses AUTOINCREMENT instead of BIGSERIAL. Otherwise
# identical.
SCHEMA_SQLITE = SCHEMA_PG.replace(
    "id            BIGSERIAL PRIMARY KEY",
    "id            INTEGER PRIMARY KEY AUTOINCREMENT",
).replace(
    "REFERENCES users(id) ON DELETE CASCADE",
    "REFERENCES users(id) ON DELETE CASCADE",  # same
)


def init_db() -> None:
    """Apply schema. Idempotent — every CREATE uses IF NOT EXISTS, and
    we additively add any missing columns on existing deployments."""
    schema = SCHEMA_PG if USE_PG else SCHEMA_SQLITE
    with connect() as conn:
        conn.executescript(schema)
        # Backfill columns added after the initial schema. Safe to run
        # every boot — no-op if the column already exists.
        _backfill_column(conn, "users", "pro_lifetime_used", "BIGINT NOT NULL DEFAULT 0")
        _backfill_column(conn, "users", "pro_daily_count", "BIGINT NOT NULL DEFAULT 0")
        _backfill_column(conn, "users", "push_token", "TEXT")


def _backfill_column(conn: _Connection, table: str, col: str, type_decl: str) -> None:
    """Add a column if it doesn't exist. Cross-DB compatible."""
    if USE_PG:
        # Postgres: information_schema query
        cur = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = ? AND column_name = ?",
            (table, col),
        )
        if cur.fetchone():
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {type_decl}")
    else:
        cur = conn.execute(f"PRAGMA table_info({table})")
        cols = {r["name"] for r in cur.fetchall()}
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {type_decl}")


# ─────────────── User helpers ───────────────


def new_user_id() -> str:
    return secrets.token_urlsafe(16)


def get_user_by_email(email: str) -> dict | None:
    with connect() as conn:
        # Postgres has no NOCASE collation; lower() on both sides works
        # for both backends.
        row = conn.execute(
            "SELECT * FROM users WHERE lower(email) = lower(?)",
            (email.strip().lower(),),
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def create_user(email: str, password_hash: str,
                display_name: str | None = None) -> dict:
    user_id = new_user_id()
    now = int(time.time())
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO users
                (id, email, password_hash, display_name, plan, created_at)
            VALUES (?, ?, ?, ?, 'free', ?)
            """,
            (user_id, email.strip().lower(), password_hash, display_name, now),
        )
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row)


def set_push_token(user_id: str, token: str | None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE users SET push_token = ? WHERE id = ?",
            (token or None, user_id),
        )


def get_push_token(user_id: str) -> str | None:
    user = get_user_by_id(user_id)
    return user.get("push_token") if user else None


def delete_user(user_id: str) -> bool:
    """Permanently delete a user and ALL their data.

    Every dependent table (sessions, generations, jobs, chats) is
    declared with ON DELETE CASCADE so a single user-row delete
    purges everything atomically. Returns True if a row was removed.

    This is the function that backs Play Store's required in-app
    'Delete account' flow. After it runs, the only trace left of the
    user is whatever's in the app-platform request logs (which roll
    off after a few weeks).
    """
    with connect() as conn:
        # Verify the user existed before we report success — otherwise
        # callers can't distinguish "deleted" from "never existed".
        before = conn.execute(
            "SELECT 1 FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not before:
            return False
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return True


# ─────────────── Job helpers ───────────────


def create_job(job_id: str, user_id: str, mode: str = "fast") -> None:
    now = int(time.time())
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, user_id, status, mode, created_at, updated_at)
            VALUES (?, ?, 'queued', ?, ?, ?)
            """,
            (job_id, user_id, mode, now, now),
        )


def update_job(
    job_id: str,
    *,
    status: str | None = None,
    contact: str | None = None,
    chat_id: str | None = None,
    result_json: str | None = None,
    error_detail: str | None = None,
) -> None:
    sets, vals = [], []
    if status is not None:
        sets.append("status = ?"); vals.append(status)
    if contact is not None:
        sets.append("contact = ?"); vals.append(contact)
    if chat_id is not None:
        sets.append("chat_id = ?"); vals.append(chat_id)
    if result_json is not None:
        sets.append("result_json = ?"); vals.append(result_json)
    if error_detail is not None:
        sets.append("error_detail = ?"); vals.append(error_detail)
    sets.append("updated_at = ?"); vals.append(int(time.time()))
    vals.append(job_id)
    with connect() as conn:
        conn.execute(
            f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?",
            vals,
        )


def get_job(job_id: str, user_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        ).fetchone()
        return dict(row) if row else None


# ─────────────── Generation tracking + quota ───────────────

DAILY_WINDOW_S = 24 * 60 * 60


def record_generation(user_id: str, model: str, cost_cents: float = 0,
                      reply_count: int = 5, mode: str = "fast") -> None:
    is_pro = mode == "pro"
    now = int(time.time())
    with connect() as conn:
        conn.execute(
            "INSERT INTO generations (user_id, ts, model, cost_cents, reply_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, now, model, cost_cents, reply_count),
        )
        row = conn.execute(
            "SELECT daily_window_start FROM users WHERE id = ?", (user_id,),
        ).fetchone()
        window_start = row["daily_window_start"] if row else 0
        rolling = not window_start or (now - window_start) >= DAILY_WINDOW_S
        if rolling:
            conn.execute(
                """
                UPDATE users
                   SET lifetime_gens_used = lifetime_gens_used + 1,
                       daily_count = 1,
                       pro_lifetime_used = pro_lifetime_used + ?,
                       pro_daily_count = ?,
                       daily_window_start = ?
                 WHERE id = ?
                """,
                (1 if is_pro else 0, 1 if is_pro else 0, now, user_id),
            )
        else:
            conn.execute(
                """
                UPDATE users
                   SET lifetime_gens_used = lifetime_gens_used + 1,
                       daily_count = daily_count + 1,
                       pro_lifetime_used = pro_lifetime_used + ?,
                       pro_daily_count = pro_daily_count + ?
                 WHERE id = ?
                """,
                (1 if is_pro else 0, 1 if is_pro else 0, user_id),
            )


def get_user_quota_state(user_id: str) -> dict:
    user = get_user_by_id(user_id)
    if not user:
        return {"valid": False}
    now = int(time.time())
    daily_count = user.get("daily_count", 0)
    pro_daily = user.get("pro_daily_count", 0)
    if user.get("daily_window_start") and (now - user["daily_window_start"]) >= DAILY_WINDOW_S:
        daily_count = 0
        pro_daily = 0
    plan = user["plan"] or "free"
    return {
        "valid": True,
        "plan": plan,
        "lifetime_used": user.get("lifetime_gens_used", 0),
        "daily_used": daily_count,
        "pro_lifetime_used": user.get("pro_lifetime_used", 0),
        "pro_daily_used": pro_daily,
        "subscription_until": user.get("subscription_until"),
        "is_subscribed": bool(
            user.get("subscription_until") and user["subscription_until"] > now
        ),
    }


# ─────────────── Tier limits ───────────────
#
# Free tier is intentionally generous. We need users to form the
# habit (~5-10 successful uses) BEFORE they hit the paywall, or they
# bounce. The cost of giving away the trial is dwarfed by LTV from
# the small percentage who convert.
#
# Pro tier is the standard subscription — comfortable for typical
# heavy users (10-15 generations/day) without abuse risk.
#
# Pro Max is the whale tier. ~5-10% of subscribers will self-select
# here and pay 2x for what feels like unlimited usage.

FREE_LIFETIME_TRIAL = 25         # Quick lifetime trial (was 8)
FREE_PRO_LIFETIME_TRIAL = 5      # Pro lifetime trial (was 2) — long enough to feel quality
FREE_DAILY_LIMIT = 5             # Quick generations/day after trial (was 3)

# Paid-tier daily caps. Quick is effectively uncapped on both paid
# tiers. Pro daily is the meaningful gate that pushes whales to upgrade.
PAID_DAILY_QUICK = 100           # Quick/day on Pro (typical user uses < 20)
PAID_DAILY_PRO = 30              # Pro/day on standard Pro
PRO_MAX_DAILY_QUICK = 200        # Quick/day on Pro Max
PRO_MAX_DAILY_PRO = 100          # Pro/day on Pro Max — effectively unlimited

# Soft signal: if a user hits any of these thresholds in their daily
# window, surface the Pro Max upsell prompt in the app. Tuned so it
# triggers for genuine power users, not casual hitters.
UPSELL_PROMPT_PRO_DAILY = 25     # 25 of 30 Pro generations used today


def _plan_caps(plan: str) -> dict:
    """Return the per-day caps applicable to a plan tier."""
    if plan == "pro_max":
        return {
            "quick_daily": PRO_MAX_DAILY_QUICK,
            "pro_daily": PRO_MAX_DAILY_PRO,
        }
    if plan == "pro":
        return {
            "quick_daily": PAID_DAILY_QUICK,
            "pro_daily": PAID_DAILY_PRO,
        }
    # free
    return {
        "quick_daily": FREE_DAILY_LIMIT,
        "pro_daily": 0,  # free tier never gets daily Pro — only the lifetime trial
    }


def can_generate(user_id: str, mode: str = "fast") -> tuple[bool, str]:
    """Returns (allowed, reason_if_not). mode is "fast" or "pro".

    Quotas:
      Free:
        - mode=fast:  lifetime trial (25) → then 5/day
        - mode=pro:   lifetime trial only (5) → then locked
      Pro ($14.99/mo):
        - mode=fast:  100/day
        - mode=pro:   30/day
      Pro Max ($29.99/mo):
        - mode=fast:  200/day
        - mode=pro:   100/day
    """
    q = get_user_quota_state(user_id)
    if not q["valid"]:
        return False, "user_not_found"

    plan = q["plan"]
    is_paid = q["is_subscribed"] and plan in ("pro", "pro_max")
    caps = _plan_caps(plan if is_paid else "free")

    if is_paid:
        if mode == "pro":
            if q["pro_daily_used"] >= caps["pro_daily"]:
                return False, "daily_cap_paid_pro"
            return True, ""
        # fast / quick
        if q["daily_used"] >= caps["quick_daily"]:
            return False, "daily_cap_paid"
        return True, ""

    # ─── Free tier ───
    if mode == "pro":
        if q["pro_lifetime_used"] < FREE_PRO_LIFETIME_TRIAL:
            return True, ""
        return False, "pro_locked_free"
    # mode=fast on free
    if q["lifetime_used"] < FREE_LIFETIME_TRIAL:
        return True, ""
    if q["daily_used"] >= FREE_DAILY_LIMIT:
        return False, "daily_cap_free"
    return True, ""


def should_show_upsell(user_id: str) -> bool:
    """True when a Pro user has been hammering the Pro daily cap and
    would benefit from upgrading to Pro Max. Used by /me to surface
    a one-time upsell prompt in the app."""
    q = get_user_quota_state(user_id)
    if not q.get("valid"):
        return False
    if q["plan"] != "pro" or not q["is_subscribed"]:
        return False
    return q["pro_daily_used"] >= UPSELL_PROMPT_PRO_DAILY


# ─────────────── Chat helpers (NEW; replaces filesystem JSON) ───────────────
#
# Each chat lives as a single row with two JSON columns: one for the
# message array, one for misc meta (last_replies, last_read,
# last_advice, source, last_copied_angle, etc). Server-side logic
# keeps the same contract as the old filesystem ChatStore but every
# call now hits the database — chats persist across redeploys + scale
# horizontally.


def _chat_id_for(user_id: str, contact: str) -> str:
    """Stable per-user-per-contact id. Same name → same row, so adding
    new messages or rerunning regenerate updates the same record."""
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in contact).strip().lower()
    return f"{user_id}:{safe}"


def chat_save(user_id: str, contact: str, messages: list[dict],
              meta: dict | None = None) -> None:
    """Upsert a chat. ``messages`` is the full ordered list (we don't
    do incremental appends in the DB layer — caller passes whatever
    they want stored). Updates last_activity_at when the message set
    has changed in any user-visible way (count or last text)."""
    chat_id = _chat_id_for(user_id, contact)
    msg_json = json.dumps(messages or [], ensure_ascii=False)
    meta_json = json.dumps(meta or {}, ensure_ascii=False)
    now = time.time()

    with connect() as conn:
        existing = conn.execute(
            "SELECT messages_json, last_activity_at FROM chats WHERE id = ?",
            (chat_id,),
        ).fetchone()

        if existing:
            # Bump last_activity only if the message set actually changed
            try:
                old_msgs = json.loads(existing["messages_json"]) or []
            except Exception:
                old_msgs = []
            old_last = old_msgs[-1].get("text", "") if old_msgs else ""
            new_last = messages[-1].get("text", "") if messages else ""
            new_activity = (
                now if (len(old_msgs) != len(messages) or old_last != new_last)
                else existing["last_activity_at"]
            )
            conn.execute(
                """
                UPDATE chats
                   SET messages_json = ?,
                       meta_json = ?,
                       last_activity_at = ?
                 WHERE id = ?
                """,
                (msg_json, meta_json, new_activity, chat_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO chats
                    (id, user_id, contact, messages_json, meta_json,
                     last_activity_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (chat_id, user_id, contact, msg_json, meta_json, now),
            )


def chat_load(user_id: str, contact: str) -> dict | None:
    """Returns ``{"messages": [...], "meta": {...}, "last_activity_at": float}``
    or None if the chat doesn't exist."""
    chat_id = _chat_id_for(user_id, contact)
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM chats WHERE id = ? AND user_id = ?",
            (chat_id, user_id),
        ).fetchone()
    if not row:
        return None
    try:
        messages = json.loads(row["messages_json"] or "[]")
    except Exception:
        messages = []
    try:
        meta = json.loads(row["meta_json"] or "{}")
    except Exception:
        meta = {}
    return {
        "id": row["id"],
        "contact": row["contact"],
        "messages": messages,
        "meta": meta,
        "last_activity_at": row["last_activity_at"] or 0,
    }


def chat_save_meta(user_id: str, contact: str, meta: dict) -> None:
    """Update meta only — leaves messages untouched. Used by reply-copy
    tracking and post-generation reply persistence."""
    chat_id = _chat_id_for(user_id, contact)
    meta_json = json.dumps(meta or {}, ensure_ascii=False)
    with connect() as conn:
        conn.execute(
            "UPDATE chats SET meta_json = ? WHERE id = ?",
            (meta_json, chat_id),
        )


def chat_list(user_id: str) -> list[dict]:
    """Returns all chats for a user, newest activity first. Lightweight
    summaries — caller calls chat_load() for full message arrays when
    needed."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, contact, messages_json, meta_json, last_activity_at "
            "FROM chats WHERE user_id = ? ORDER BY last_activity_at DESC",
            (user_id,),
        ).fetchall()
    out = []
    for r in rows:
        try:
            msgs = json.loads(r["messages_json"] or "[]")
        except Exception:
            msgs = []
        try:
            meta = json.loads(r["meta_json"] or "{}")
        except Exception:
            meta = {}
        out.append({
            "id": r["id"],
            "contact": r["contact"],
            "messages": msgs,
            "meta": meta,
            "last_activity_at": r["last_activity_at"] or 0,
        })
    return out


def chat_delete(user_id: str, contact_or_id: str) -> None:
    """Delete by either contact name or stored id (the chat list returns
    ids; the mobile API also passes contact names sometimes)."""
    by_id = contact_or_id
    by_contact_id = _chat_id_for(user_id, contact_or_id)
    with connect() as conn:
        conn.execute(
            "DELETE FROM chats WHERE user_id = ? AND (id = ? OR id = ?)",
            (user_id, by_id, by_contact_id),
        )
