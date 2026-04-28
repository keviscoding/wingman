"""Production SaaS entry point.

Lives separate from ``server.app`` (the desktop control panel) on
purpose: that file imports the entire desktop orchestrator including
OpenCV, mss, pyobjc, etc. — all unavailable on the Linux server
container.

This file ONLY mounts the multi-tenant ``/api/v1`` routes. Static UI,
Wingman class, hotkey, screen capture, voice — none of it loads here.
The mobile app talks exclusively to this surface.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from wingman.saas import db as _saas_db
from wingman.saas.routes import router as _saas_router


def _bootstrap_gcp_credentials() -> None:
    """Materialize a Google Cloud service-account JSON from env into a
    file on disk, then point Google libraries at it.

    DO App Platform doesn't give us a way to upload files, so we ship
    the JSON as an env var (`GOOGLE_APPLICATION_CREDENTIALS_JSON`) and
    re-hydrate it here on every container boot. Vertex AI auth reads
    from `GOOGLE_APPLICATION_CREDENTIALS`, which is what we set after
    writing the file.

    Robustness layers (DO mangles multi-line env values in subtle ways
    depending on how they're pasted, so we try each format until we
    get something parseable):

      1. Direct JSON — the happy path
      2. Escaped JSON — value contains literal "\\n" / "\\\"" pairs;
         we un-escape and try again
      3. Base64 — operator can paste base64(json) instead which is
         escape-proof; we detect by JSON-parse failing then
         attempting base64 decode

    If all three fail we log a redacted preview so the operator can
    diagnose without leaking the SA private key.

    Skipped silently if the env var isn't set — AI Studio key path
    keeps working either way.
    """
    import base64 as _b64
    import json as _json

    raw = (os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON") or "").strip()
    if not raw:
        return

    def _try_parse(s: str) -> dict | None:
        try:
            return _json.loads(s)
        except Exception:
            return None

    parsed = _try_parse(raw)
    fmt = "direct"

    # Layer 2: env value contains escaped newlines / quotes (DO does
    # this with multi-line paste sometimes).
    if parsed is None:
        unescaped = raw.encode("utf-8").decode("unicode_escape")
        parsed = _try_parse(unescaped)
        if parsed is not None:
            raw = unescaped
            fmt = "unescaped"

    # Layer 3: operator pasted base64 instead. Recommended path for DO.
    if parsed is None:
        try:
            decoded = _b64.b64decode(raw, validate=False).decode("utf-8")
            parsed = _try_parse(decoded)
            if parsed is not None:
                raw = decoded
                fmt = "base64"
        except Exception:
            pass

    if parsed is None:
        # All three formats failed. Log a redacted preview to help
        # the operator diagnose without leaking the private key.
        preview = raw[:120].replace("\n", "\\n")
        print(
            f"[saas] GOOGLE_APPLICATION_CREDENTIALS_JSON could not be parsed "
            f"as direct JSON, escaped JSON, or base64. "
            f"length={len(raw)} preview={preview!r}"
        )
        return

    # Sanity-check the parsed payload looks like a service account.
    sa_email = parsed.get("client_email") or "<missing>"
    sa_project = parsed.get("project_id") or "<missing>"

    target = "/tmp/gcp-creds.json"
    try:
        with open(target, "w", encoding="utf-8") as f:
            _json.dump(parsed, f)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = target
        print(
            f"[saas] Wrote GCP credentials to {target} "
            f"(format={fmt}, sa={sa_email}, project={sa_project})"
        )
    except Exception as exc:
        print(f"[saas] Failed to write GCP creds to disk: {exc}")


def _seed_persistent_account() -> None:
    """Ensure a fixed Pro account exists after every container boot.

    On DO Basic instances the SQLite DB lives on ephemeral disk — every
    redeploy wipes user data. Until we migrate to managed Postgres, this
    seeder lets the operator set WINGMAN_SEED_PRO_EMAIL and
    WINGMAN_SEED_PRO_PASSWORD env vars; on startup we create-or-update
    the account with those credentials and set it to Pro for a year.

    Idempotent: safe to run on every boot. If the account already exists
    we just refresh the password hash + extend the subscription.
    """
    email = (os.getenv("WINGMAN_SEED_PRO_EMAIL") or "").strip().lower()
    password = (os.getenv("WINGMAN_SEED_PRO_PASSWORD") or "").strip()
    if not email or not password:
        return
    try:
        from wingman.saas import auth, db
        import time as _time

        existing = db.get_user_by_email(email)
        pw_hash = auth.hash_password(password)
        until = int(_time.time()) + 365 * 24 * 3600

        # Seed account is always Pro Max so the operator can test
        # unconstrained — paid limits don't get in the way of QA.
        if existing:
            with db.connect() as conn:
                conn.execute(
                    "UPDATE users SET password_hash = ?, plan = 'pro_max', "
                    "subscription_until = ? WHERE id = ?",
                    (pw_hash, until, existing["id"]),
                )
            print(f"[seed] Refreshed Pro Max account: {email}")
        else:
            user = db.create_user(email, pw_hash, display_name="Pro Max")
            with db.connect() as conn:
                conn.execute(
                    "UPDATE users SET plan = 'pro_max', subscription_until = ? "
                    "WHERE id = ?",
                    (until, user["id"]),
                )
            print(f"[seed] Created Pro Max account: {email}")
    except Exception as exc:
        print(f"[seed] Failed: {exc}")


_bootstrap_gcp_credentials()
_saas_db.init_db()
_seed_persistent_account()

app = FastAPI(
    title="Wingman SaaS",
    description="Multi-tenant API for the Wingman mobile app.",
    version="1.0.0",
)

# CORS — wide-open is fine for this product. The mobile app sends
# Authorization: Bearer <jwt>, which is what protects every endpoint.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(_saas_router)


# Liveness / readiness — DO's health check pings this. Kept dirt-simple
# so it never returns 5xx even if a downstream Gemini call is failing.
@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "wingman-saas"}


# Keep the legacy desktop-style readiness probe path working too, since
# .do/app.yaml currently points at `/api/state`. Cheap to maintain.
@app.get("/api/state")
async def state_compat() -> dict:
    return {"ok": True, "mode": "saas"}


@app.get("/")
async def index() -> dict:
    return {
        "service": "wingman",
        "status": "ok",
        "endpoints": {
            "auth": "/api/v1/auth/{signup,login}",
            "me": "/api/v1/me",
            "quick_capture": "/api/v1/quick-capture",
            "chats": "/api/v1/chats",
        },
    }


@app.get("/diag/db")
async def diag_db() -> dict:
    """Confirm which backend (Postgres vs SQLite) the running container
    is actually using, plus a row-count sanity check on the users table.
    Used to verify the DATABASE_URL injection took effect after the
    Postgres migration deploy."""
    try:
        from wingman.saas import db
        with db.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
            users = row["n"] if row else 0
            row2 = conn.execute("SELECT COUNT(*) AS n FROM chats").fetchone()
            chats = row2["n"] if row2 else 0
        return {
            "backend": "postgres" if db.USE_PG else "sqlite",
            "users": users,
            "chats": chats,
        }
    except Exception as exc:
        return {"backend": "error", "error": str(exc)}


@app.get("/diag/extract")
async def diag_extract() -> dict:
    """Test that the Flash Lite extraction call can reach Gemini.
    Returns the first 80 chars of a mock response. Useful to confirm
    GEMINI_API_KEYS is populated and the API surface is reachable."""
    try:
        from wingman.config import make_genai_client, FLASH_LITE_MODEL, _ALL_KEYS
        if not _ALL_KEYS:
            return {"ok": False, "error": "no_gemini_keys"}
        client = make_genai_client()
        from google.genai import types as gtypes
        resp = client.models.generate_content(
            model=FLASH_LITE_MODEL,
            contents="Say only the word: OK",
            config=gtypes.GenerateContentConfig(
                temperature=0.0, max_output_tokens=16,
            ),
        )
        text = (resp.text or "").strip()
        return {"ok": True, "model": FLASH_LITE_MODEL, "preview": text[:80], "key_count": len(_ALL_KEYS)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


@app.get("/diag/playbook")
async def diag_playbook() -> dict:
    """Diagnostic — confirms the Master Playbook is loaded into the
    running process. Returns size + first 200 chars (enough to see
    'Master Playbook' / 'Playing With Fire' in the response). If
    chars=0 or status != 'loaded', Pro generations are running with
    no playbook and replies will be vanilla Gemini.
    """
    try:
        from wingman.training_rag import TrainingRAG
        rag = TrainingRAG()
        rag.load()
        pb = rag.knowledge_summary or ""
        return {
            "status": rag.status,
            "chars": len(pb),
            "preview": pb[:200],
        }
    except Exception as exc:
        return {"status": "error", "chars": 0, "error": str(exc)}
