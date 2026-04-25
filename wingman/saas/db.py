"""SQLite-backed user store. Intentionally minimal — bigger plans
later (move to Postgres on Railway when we scale). For MVP, SQLite
gives us atomic writes, indexed lookups, and zero infra to manage.

Schema:
  users        — accounts (id, email, password_hash, created_at,
                  display_name, plan, lifetime_gens_used, daily_count,
                  daily_window_start)
  sessions     — JWT refresh tracking (optional, primarily for revoke)
  generations  — audit trail of every reply call (id, user_id, ts, cost_cents)

Why audit-trail every generation? Three reasons:
  1. Quota enforcement against gaming the daily window
  2. Cost-per-user analytics (margin tracking)
  3. Future training data: 'best replies by usage' if a user copies one
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


DB_PATH = Path(os.getenv("WINGMAN_SAAS_DB", "data/saas/wingman.sqlite3"))


def _ensure_dir() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Per-call connection. SQLite is fine for our scale; no pool needed."""
    _ensure_dir()
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id                   TEXT PRIMARY KEY,
  email                TEXT NOT NULL UNIQUE,
  password_hash        TEXT NOT NULL,
  display_name         TEXT,
  plan                 TEXT NOT NULL DEFAULT 'free',
  -- counters used to enforce quotas without scanning generations table
  lifetime_gens_used   INTEGER NOT NULL DEFAULT 0,
  daily_count          INTEGER NOT NULL DEFAULT 0,
  -- High-quality (Pro) generations are gated separately from Fast.
  -- Free trial: 2 lifetime Pro to taste-test, then locked to paid users.
  pro_lifetime_used    INTEGER NOT NULL DEFAULT 0,
  pro_daily_count      INTEGER NOT NULL DEFAULT 0,
  -- start of the current rolling 24h window (epoch seconds)
  daily_window_start   INTEGER NOT NULL DEFAULT 0,
  created_at           INTEGER NOT NULL,
  -- nullable: when subscription expires; NULL means free tier
  subscription_until   INTEGER
);

CREATE TABLE IF NOT EXISTS sessions (
  jti           TEXT PRIMARY KEY,           -- JWT id
  user_id       TEXT NOT NULL,
  issued_at     INTEGER NOT NULL,
  expires_at    INTEGER NOT NULL,
  revoked       INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);

CREATE TABLE IF NOT EXISTS generations (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id       TEXT NOT NULL,
  ts            INTEGER NOT NULL,
  model         TEXT NOT NULL,         -- pro / flash / tuned-v4 / deepseek / ...
  cost_cents    REAL NOT NULL DEFAULT 0,
  reply_count   INTEGER NOT NULL DEFAULT 5,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS generations_user_idx ON generations(user_id, ts);
"""


def init_db() -> None:
    """Apply SCHEMA. ``executescript`` handles multi-statement DDL
    including inline comments — safer than naive split-on-semicolon
    which gets confused by comments / string literals.

    Runs an idempotent migration after CREATE TABLE so an existing
    `users` table from a prior deploy gets the new pro-quota columns
    backfilled to defaults (SQLite ALTER TABLE ADD COLUMN).
    """
    with connect() as conn:
        conn.executescript(SCHEMA)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "pro_lifetime_used" not in cols:
            conn.execute(
                "ALTER TABLE users ADD COLUMN pro_lifetime_used INTEGER NOT NULL DEFAULT 0"
            )
        if "pro_daily_count" not in cols:
            conn.execute(
                "ALTER TABLE users ADD COLUMN pro_daily_count INTEGER NOT NULL DEFAULT 0"
            )


# ---------------------------------------------------------------------------
# User helpers (small surface — auth.py handles password hashing)
# ---------------------------------------------------------------------------


def new_user_id() -> str:
    """URL-safe random id. 22 chars of entropy = 132 bits."""
    return secrets.token_urlsafe(16)


def get_user_by_email(email: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE",
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
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row)


# ---------------------------------------------------------------------------
# Generation tracking + quota helpers
# ---------------------------------------------------------------------------

DAILY_WINDOW_S = 24 * 60 * 60


def record_generation(user_id: str, model: str, cost_cents: float = 0,
                      reply_count: int = 5, mode: str = "fast") -> None:
    """Atomically: log the generation, increment user counters, roll the
    daily window if a day has elapsed. Single transaction so quota
    can't be raced.

    `mode` is "fast" or "pro". Both update the global lifetime/daily
    counters; pro additionally bumps pro_lifetime_used / pro_daily_count
    so we can gate the high-quality model independently.
    """
    is_pro = mode == "pro"
    now = int(time.time())
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO generations (user_id, ts, model, cost_cents, reply_count)
            VALUES (?, ?, ?, ?, ?)
            """,
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
    # Auto-roll daily window if expired so the read is always fresh.
    daily_count = user["daily_count"]
    pro_daily = user["pro_daily_count"] if "pro_daily_count" in user.keys() else 0
    if user["daily_window_start"] and (now - user["daily_window_start"]) >= DAILY_WINDOW_S:
        daily_count = 0
        pro_daily = 0
    return {
        "valid": True,
        "plan": user["plan"],
        "lifetime_used": user["lifetime_gens_used"],
        "daily_used": daily_count,
        "pro_lifetime_used": user["pro_lifetime_used"] if "pro_lifetime_used" in user.keys() else 0,
        "pro_daily_used": pro_daily,
        "subscription_until": user["subscription_until"],
        "is_subscribed": bool(
            user["subscription_until"] and user["subscription_until"] > now
        ),
    }


# Free tier limits — we change these centrally, never hard-code in routes
FREE_LIFETIME_TRIAL = 8        # Fast trials (the "default" model)
FREE_PRO_LIFETIME_TRIAL = 2    # Pro trials — taster, then locked
FREE_DAILY_LIMIT = 3           # Fast generations per rolling 24h after trial
PAID_DAILY_LIMIT = 200         # Abuse cap for paid users (Fast OR Pro)


def can_generate(user_id: str, mode: str = "fast") -> tuple[bool, str]:
    """Returns (allowed, reason_if_not). Reason strings are
    machine-friendly so the mobile app can render specific UI.

    `mode` is "fast" or "pro" — Pro is gated tighter on free accounts.
    """
    q = get_user_quota_state(user_id)
    if not q["valid"]:
        return False, "user_not_found"
    if q["is_subscribed"]:
        if q["daily_used"] >= PAID_DAILY_LIMIT:
            return False, "daily_cap_paid"
        return True, ""
    # Free tier
    if mode == "pro":
        # Free Pro is lifetime-trial only — no daily refill after.
        if q["pro_lifetime_used"] < FREE_PRO_LIFETIME_TRIAL:
            return True, ""
        return False, "pro_locked_free"
    # Fast mode: lifetime trial first, then daily allowance
    if q["lifetime_used"] < FREE_LIFETIME_TRIAL:
        return True, ""
    if q["daily_used"] >= FREE_DAILY_LIMIT:
        return False, "daily_cap_free"
    return True, ""
