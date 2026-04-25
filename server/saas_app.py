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
    re-hydrate it here on every container boot. Vertex AI auth (used by
    the tuned Flash client) reads from `GOOGLE_APPLICATION_CREDENTIALS`,
    which is what we set after writing the file.

    Skipped silently if the env var isn't set — Pro mode (public Gemini
    API key) keeps working either way.
    """
    raw = (os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON") or "").strip()
    if not raw:
        return
    target = "/tmp/gcp-creds.json"
    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write(raw)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = target
        print(f"[saas] Wrote GCP credentials to {target}")
    except Exception as exc:
        print(f"[saas] Failed to write GCP creds: {exc}")


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

        if existing:
            with db.connect() as conn:
                conn.execute(
                    "UPDATE users SET password_hash = ?, plan = 'pro', "
                    "subscription_until = ? WHERE id = ?",
                    (pw_hash, until, existing["id"]),
                )
            print(f"[seed] Refreshed Pro account: {email}")
        else:
            user = db.create_user(email, pw_hash, display_name="Pro")
            with db.connect() as conn:
                conn.execute(
                    "UPDATE users SET plan = 'pro', subscription_until = ? "
                    "WHERE id = ?",
                    (until, user["id"]),
                )
            print(f"[seed] Created Pro account: {email}")
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
