"""Mobile-facing REST API.

Mounted at ``/api/v1`` only when ``WINGMAN_MODE=saas``. Everything is
JWT-protected except auth endpoints. The mobile app talks to nothing
else.

Endpoints (MVP):
  POST /api/v1/auth/signup       — email + password → JWT
  POST /api/v1/auth/login        — email + password → JWT
  GET  /api/v1/me                — current user + quota state

  POST /api/v1/quick-capture     — upload screenshot → 5 replies in one call
                                    (the killer endpoint — zero-tap UX)

  GET  /api/v1/chats             — list user's chats
  GET  /api/v1/chats/{id}        — full chat state + last replies
  POST /api/v1/chats/{id}/regenerate — new replies for an existing chat
  DELETE /api/v1/chats/{id}      — delete chat

  POST /api/v1/replies/{chat_id}/copy — track a copy event (analytics + future
                                          training signal)

The pipeline that actually generates the replies — extraction, tuned
v4 model, examples library, case studies, etc. — runs the same way as
in personal mode, just operating on user-scoped data via UserContext.
"""

from __future__ import annotations

import asyncio
import base64
import io
import time
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from . import auth, db
from .user_context import UserContext, get_context


router = APIRouter(prefix="/api/v1")


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


def _bearer_token(authorization: Annotated[str | None, Header()] = None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


def current_user(authorization: Annotated[str | None, Header()] = None) -> dict:
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    payload = auth.verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="bad_token_payload")
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="user_not_found")
    return user


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=80)


class AuthResponse(BaseModel):
    token: str
    expires_at: int           # epoch seconds
    user_id: str
    email: str
    plan: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/auth/signup", response_model=AuthResponse)
async def signup(body: SignupRequest):
    if db.get_user_by_email(body.email):
        raise HTTPException(status_code=409, detail="email_already_registered")
    pw_hash = auth.hash_password(body.password)
    user = db.create_user(body.email, pw_hash, body.display_name)
    token, exp = auth.issue_token(user["id"])
    return AuthResponse(
        token=token, expires_at=exp,
        user_id=user["id"], email=user["email"], plan=user["plan"],
    )


@router.post("/auth/login", response_model=AuthResponse)
async def login(body: LoginRequest):
    user = auth.authenticate(body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="invalid_credentials")
    token, exp = auth.issue_token(user["id"])
    return AuthResponse(
        token=token, expires_at=exp,
        user_id=user["id"], email=user["email"], plan=user["plan"],
    )


# ---------------------------------------------------------------------------
# Me / quota
# ---------------------------------------------------------------------------


class MeResponse(BaseModel):
    user_id: str
    email: str
    display_name: str | None
    plan: str
    is_subscribed: bool
    subscription_until: int | None
    lifetime_used: int
    daily_used: int
    pro_lifetime_used: int = 0
    pro_daily_used: int = 0
    # Tier-aware caps for mobile UI
    quick_daily_cap: int = 0
    pro_daily_cap: int = 0
    free_lifetime_trial: int = db.FREE_LIFETIME_TRIAL
    free_pro_lifetime_trial: int = db.FREE_PRO_LIFETIME_TRIAL
    free_daily_limit: int = db.FREE_DAILY_LIMIT
    paid_daily_limit: int = db.PAID_DAILY_QUICK
    # Server-detected upsell — true when a Pro user has been
    # consistently hitting the Pro daily cap.
    should_show_pro_max_upsell: bool = False


class PushTokenRequest(BaseModel):
    token: str | None = None


@router.post("/me/push-token")
async def register_push_token(
    body: PushTokenRequest,
    user: Annotated[dict, Depends(current_user)],
):
    """Mobile reports its Expo Push Token here on every app launch.
    We persist it on the user row; subsequent generation completions
    fire a push to whichever device last reported.

    Pass `token: null` (or omit) on sign-out to clear it.
    """
    db.set_push_token(user["id"], body.token)
    return {"ok": True}


@router.post("/me/test-push")
async def test_push(user: Annotated[dict, Depends(current_user)]):
    """Diagnostic — fires a notification immediately to the user's
    last-registered Expo push token. Use this to verify the push
    pipeline (token registration → Expo Push API → device) works
    independently of any generation.
    """
    token = db.get_push_token(user["id"])
    if not token:
        raise HTTPException(
            status_code=400,
            detail="no_push_token_registered",
        )
    from .push import send_expo_push
    await send_expo_push(
        token,
        title="Wingman test ✓",
        body="If you see this, push notifications work.",
        data={"test": True},
    )
    return {"ok": True, "token_prefix": token[:30]}


@router.delete("/me")
async def delete_me(user: Annotated[dict, Depends(current_user)]):
    """In-app account deletion. Required by Google Play and Apple App
    Store for any app that supports account creation.

    Removes the user row, which cascades to:
      - sessions (any active JWTs become invalid on next request since
        we look up the user by id)
      - generations audit log
      - jobs queue (running and historical)
      - chats (messages, replies, meta)

    Idempotent — calling this twice for an already-deleted user just
    returns ok:true. Mobile signs out client-side after the call so
    the local JWT is forgotten.
    """
    db.delete_user(user["id"])
    return {"ok": True, "deleted_user_id": user["id"]}


@router.get("/me", response_model=MeResponse)
async def me(user: Annotated[dict, Depends(current_user)]):
    q = db.get_user_quota_state(user["id"])
    plan = q["plan"]
    is_paid = q["is_subscribed"] and plan in ("pro", "pro_max")
    caps = db._plan_caps(plan if is_paid else "free")
    return MeResponse(
        user_id=user["id"],
        email=user["email"],
        display_name=user.get("display_name"),
        plan=plan,
        is_subscribed=q["is_subscribed"],
        subscription_until=q.get("subscription_until"),
        lifetime_used=q["lifetime_used"],
        daily_used=q["daily_used"],
        pro_lifetime_used=q.get("pro_lifetime_used", 0),
        pro_daily_used=q.get("pro_daily_used", 0),
        quick_daily_cap=caps["quick_daily"],
        pro_daily_cap=caps["pro_daily"],
        should_show_pro_max_upsell=db.should_show_upsell(user["id"]),
    )


# ---------------------------------------------------------------------------
# Quick-capture: the killer endpoint
# ---------------------------------------------------------------------------


class ReplyOption(BaseModel):
    label: str
    text: str
    why: str = ""


class QuickCaptureResponse(BaseModel):
    chat_id: str
    contact: str
    transcript: list[dict]    # [{speaker, text}, ...]
    replies: list[ReplyOption]
    read: str = ""
    advice: str = ""
    generated_at: int
    model: str


class QueuedJobResponse(BaseModel):
    job_id: str
    status: str = "queued"


@router.post("/quick-capture", response_model=QueuedJobResponse, status_code=202)
async def quick_capture(
    user: Annotated[dict, Depends(current_user)],
    screenshot: UploadFile = File(...),
    extra_context: str = Form(default=""),
    mode: str = Form(default="fast"),
):
    """Async quick-capture: returns immediately (~1-3s) with a job_id.

    The slow work — Flash extraction, reply generation, push delivery —
    happens in a background asyncio task. The mobile client either
    polls `/jobs/{id}` or just waits for the system push notification
    (or both).

    This is the architectural fix that makes background-and-come-back
    work: the upload completes BEFORE Android suspends JS, so the
    server always knows the user wanted a generation. From there
    everything is server-driven.
    """
    if mode not in ("fast", "pro"):
        mode = "fast"

    allowed, reason = db.can_generate(user["id"], mode=mode)
    if not allowed:
        raise HTTPException(status_code=402, detail=reason)

    img_bytes = await screenshot.read()
    if len(img_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="image_too_large")

    ctx = get_context(user["id"], plan=user.get("plan", "free"))

    import secrets
    job_id = secrets.token_urlsafe(16)
    db.create_job(job_id, user["id"], mode=mode)

    # Kick the actual generation onto a background task. We deliberately
    # don't await it — the client gets the job_id back in <1s.
    asyncio.create_task(
        _process_job(
            job_id=job_id,
            user_id=user["id"],
            ctx=ctx,
            img_bytes=img_bytes,
            extra_context=extra_context,
            mode=mode,
        )
    )

    return QueuedJobResponse(job_id=job_id)


async def _process_job(
    *,
    job_id: str,
    user_id: str,
    ctx,
    img_bytes: bytes,
    extra_context: str,
    mode: str,
) -> None:
    """Background worker — runs generation, updates DB, fires push.
    Never raises (all exceptions land in the job's error_detail)."""
    import json as _json
    from .pipeline import quick_capture_for_user

    db.update_job(job_id, status="running")
    try:
        result = await quick_capture_for_user(
            ctx, img_bytes, extra_context=extra_context, mode=mode,
        )
        if not result.get("replies"):
            db.update_job(job_id, status="error", error_detail="no_replies_produced")
            return

        db.record_generation(
            user_id=user_id,
            model=result.get("model", "unknown"),
            cost_cents=result.get("cost_cents", 0),
            reply_count=len(result["replies"]),
            mode=mode,
        )

        payload = {
            "job_id": job_id,
            "chat_id": result["chat_id"],
            "contact": result["contact"],
            "transcript": result["transcript"],
            "replies": result["replies"],
            "read": result.get("read", ""),
            "advice": result.get("advice", ""),
            "generated_at": int(time.time()),
            "model": result.get("model", "tuned-v4"),
        }
        db.update_job(
            job_id,
            status="ready",
            contact=result["contact"],
            chat_id=result["chat_id"],
            result_json=_json.dumps(payload, ensure_ascii=False),
        )

        # Push — independent of whether the client is still listening.
        push_token = db.get_push_token(user_id)
        if push_token:
            from .push import send_expo_push
            await send_expo_push(
                push_token,
                title="Your reply is ready ✓",
                body=f"5 replies for {result.get('contact', 'your chat')} · tap to copy",
                data={
                    "job_id": job_id,
                    "chat_id": result["chat_id"],
                    "contact": result.get("contact"),
                },
            )
    except Exception as exc:
        import traceback
        traceback.print_exc()
        db.update_job(
            job_id,
            status="error",
            error_detail=str(exc)[:500],
        )


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    mode: str | None = None
    contact: str | None = None
    chat_id: str | None = None
    error_detail: str | None = None
    # Full QuickCaptureResponse-shaped dict when status === "ready".
    result: dict | None = None


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(
    job_id: str,
    user: Annotated[dict, Depends(current_user)],
):
    """Mobile polls this to check job status. Returns the same payload
    shape the old quick-capture used to return, embedded under `result`
    when the job is `ready`.
    """
    row = db.get_job(job_id, user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="job_not_found")
    result = None
    if row["status"] == "ready" and row["result_json"]:
        import json as _json
        try:
            result = _json.loads(row["result_json"])
        except Exception:
            result = None
    return JobStatusResponse(
        job_id=row["id"],
        status=row["status"],
        mode=row.get("mode"),
        contact=row.get("contact"),
        chat_id=row.get("chat_id"),
        error_detail=row.get("error_detail"),
        result=result,
    )


# ---------------------------------------------------------------------------
# Chat list / detail / regenerate / delete
# ---------------------------------------------------------------------------


@router.get("/chats")
async def list_chats(user: Annotated[dict, Depends(current_user)]):
    from .pipeline import list_chats_for_user
    return list_chats_for_user(get_context(user["id"]))


@router.get("/chats/{chat_id}")
async def get_chat(
    chat_id: str,
    user: Annotated[dict, Depends(current_user)],
):
    from .pipeline import get_chat_for_user
    data = get_chat_for_user(get_context(user["id"]), chat_id)
    if not data:
        raise HTTPException(status_code=404, detail="chat_not_found")
    return data


class RegenerateRequest(BaseModel):
    extra_context: str = ""
    mode: str = "fast"


@router.post("/chats/{chat_id}/regenerate")
async def regenerate(
    chat_id: str,
    body: RegenerateRequest,
    user: Annotated[dict, Depends(current_user)],
):
    mode = body.mode if body.mode in ("fast", "pro") else "fast"
    allowed, reason = db.can_generate(user["id"], mode=mode)
    if not allowed:
        raise HTTPException(status_code=402, detail=reason)
    from .pipeline import regenerate_for_user
    try:
        result = await regenerate_for_user(
            get_context(user["id"]), chat_id,
            extra_context=body.extra_context,
            mode=mode,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="chat_not_found")
    except Exception:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="generation_failed")
    if not result.get("replies"):
        raise HTTPException(status_code=502, detail="no_replies_produced")
    db.record_generation(
        user_id=user["id"],
        model=result.get("model", "unknown"),
        cost_cents=result.get("cost_cents", 0),
        reply_count=len(result["replies"]),
        mode=mode,
    )
    push_token = db.get_push_token(user["id"])
    if push_token:
        from .push import fire_and_forget
        fire_and_forget(
            push_token,
            title="Fresh replies ready ✓",
            body=f"New replies for {result.get('contact', 'your chat')} · tap to view",
            data={
                "chat_id": result.get("chat_id", chat_id),
                "contact": result.get("contact"),
            },
        )
    return result


class LockedContextRequest(BaseModel):
    locked_context: str = ""
    enabled: bool = True


@router.patch("/chats/{chat_id}/context")
async def set_locked_context(
    chat_id: str,
    body: LockedContextRequest,
    user: Annotated[dict, Depends(current_user)],
):
    """Pin a piece of context to a specific chat so it auto-merges into
    every future generation for that chat (regenerate + new
    screenshots). Lets the user type "she's vegan, has a Pomeranian
    named Biscuit" once and have Muzo remember forever.

    Sending ``enabled=False`` disables the lock without deleting the
    text — toggle in/out without re-typing.
    Sending ``locked_context=""`` clears it entirely.
    """
    chat = db.chat_load(user["id"], chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="chat_not_found")
    meta = dict(chat.get("meta") or {})
    meta["locked_context"] = (body.locked_context or "").strip()
    meta["locked_context_enabled"] = bool(body.enabled and meta["locked_context"])
    db.chat_save_meta(user["id"], chat_id, meta)
    return {
        "ok": True,
        "locked_context": meta["locked_context"],
        "locked_context_enabled": meta["locked_context_enabled"],
    }


@router.delete("/chats/{chat_id}")
async def delete_chat(
    chat_id: str,
    user: Annotated[dict, Depends(current_user)],
):
    from .pipeline import delete_chat_for_user
    delete_chat_for_user(get_context(user["id"]), chat_id)
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Reply copy tracking (analytics + future training signal)
# ---------------------------------------------------------------------------


class CopyEventRequest(BaseModel):
    label: str
    text: str


@router.post("/replies/{chat_id}/copy")
async def reply_copied(
    chat_id: str,
    body: CopyEventRequest,
    user: Annotated[dict, Depends(current_user)],
):
    """User tapped 'copy' on a reply. Cheap to log; valuable signal:
    these are the replies users actually send. Future v5 training can
    weight these higher than raw Pro distillation."""
    from .pipeline import record_reply_copy
    record_reply_copy(get_context(user["id"]), chat_id, body.label, body.text)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin (operator-only) — granting Pro to test / friends-and-family accounts
# ---------------------------------------------------------------------------

class AdminUpgradeRequest(BaseModel):
    email: EmailStr
    days: int = 365
    plan: str = "pro"  # "pro" or "pro_max"


def _admin_token(authorization: Annotated[str | None, Header()] = None) -> str | None:
    """Same Bearer token format as user auth, but checked against
    WINGMAN_ADMIN_TOKEN env var instead of the user JWT."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


def require_admin(authorization: Annotated[str | None, Header()] = None):
    import os
    expected = (os.getenv("WINGMAN_ADMIN_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="admin_disabled")
    token = _admin_token(authorization)
    if not token or token != expected:
        raise HTTPException(status_code=401, detail="bad_admin_token")
    return True


@router.post("/admin/upgrade")
async def admin_upgrade(
    body: AdminUpgradeRequest,
    _admin: Annotated[bool, Depends(require_admin)],
):
    """Grant a user a Pro subscription for ``days`` days.

    Use sparingly — for comp accounts, beta testers, refunded users.
    Auth is a single shared token in WINGMAN_ADMIN_TOKEN; rotate it
    periodically.
    """
    user = db.get_user_by_email(body.email)
    if not user:
        raise HTTPException(status_code=404, detail="user_not_found")
    plan = body.plan if body.plan in ("pro", "pro_max") else "pro"
    until = int(time.time()) + body.days * 24 * 3600
    with db.connect() as conn:
        conn.execute(
            "UPDATE users SET plan = ?, subscription_until = ? WHERE id = ?",
            (plan, until, user["id"]),
        )
    return {"ok": True, "email": body.email, "plan": plan, "subscription_until": until}


# ---------------------------------------------------------------------------
# RevenueCat webhook — receives real-time purchase events from Play / App
# Store via RevenueCat. Maps RC entitlements -> users.plan in Postgres so
# the mobile app's /me reflects the new subscription state immediately.
# ---------------------------------------------------------------------------
#
# RC sends one event per state change: INITIAL_PURCHASE, RENEWAL,
# CANCELLATION, EXPIRATION, NON_RENEWING_PURCHASE, BILLING_ISSUE,
# PRODUCT_CHANGE, TRANSFER, etc.
#
# We map these to two mutations on the users table:
#   - When entitlement is active  → set plan = 'pro' or 'pro_max',
#                                   set subscription_until = expires_at
#   - When entitlement expires    → set plan = 'free', clear sub_until
#
# RC posts JSON like:
#   {
#     "event": {
#       "type": "INITIAL_PURCHASE",
#       "app_user_id": "<our user_id>",
#       "product_id": "pro_max_weekly",
#       "entitlement_ids": ["pro_max"],
#       "expiration_at_ms": 1750000000000,
#       ...
#     }
#   }
#
# Auth: RC signs every request with a configurable Bearer token in
# the Authorization header. Set REVENUECAT_WEBHOOK_TOKEN to match
# whatever you configured in the RC dashboard. We reject any request
# without the matching token to prevent spoofing.

class RevenueCatEvent(BaseModel):
    event: dict


def _verify_rc_token(authorization: Annotated[str | None, Header()] = None) -> None:
    import os
    expected = (os.getenv("REVENUECAT_WEBHOOK_TOKEN") or "").strip()
    if not expected:
        # Webhook not configured server-side — fail open in dev so
        # we can test, but log loudly so we notice.
        print("[rc-webhook] REVENUECAT_WEBHOOK_TOKEN not set — accepting all events")
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="bad_rc_token")
    token = authorization.split(None, 1)[1].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="bad_rc_token")


def _plan_from_entitlements(ent_ids: list[str]) -> str | None:
    """Pick the highest tier the user is entitled to.

    Pro Max wins over Pro if both are somehow active simultaneously
    (shouldn't happen in practice but defend against it).
    """
    if "pro_max" in ent_ids:
        return "pro_max"
    if "pro" in ent_ids:
        return "pro"
    return None


@router.post("/webhooks/revenuecat")
async def revenuecat_webhook(
    body: RevenueCatEvent,
    _auth: Annotated[None, Depends(_verify_rc_token)],
):
    e = body.event or {}
    event_type = (e.get("type") or "").upper()
    user_id = e.get("app_user_id") or ""
    ent_ids = list(e.get("entitlement_ids") or [])
    expires_ms = e.get("expiration_at_ms")
    product_id = e.get("product_id") or ""

    print(
        f"[rc-webhook] type={event_type} user={user_id} ent={ent_ids} "
        f"product={product_id} expires_ms={expires_ms}"
    )

    if not user_id:
        # Anonymous events (e.g. TEST events RC sends to verify the
        # webhook URL) — accept and no-op.
        return {"ok": True, "noop": "no_user_id"}

    user = db.get_user_by_id(user_id)
    if not user:
        # Probably a test event with a fake user id, or a user we
        # deleted. Don't 500 — RC retries on 5xx.
        return {"ok": True, "noop": "user_not_found"}

    # Active entitlement events → upgrade the plan
    active_events = {
        "INITIAL_PURCHASE",
        "RENEWAL",
        "PRODUCT_CHANGE",
        "UNCANCELLATION",
        "NON_RENEWING_PURCHASE",
        "TRANSFER",
    }
    # Inactive events → demote to free
    inactive_events = {
        "EXPIRATION",
        "CANCELLATION",  # user cancelled — RC sends CANCELLATION
                         # but the entitlement stays active until
                         # EXPIRATION, so we don't actually demote here.
                         # Keeping this here for future logic; for now
                         # only EXPIRATION demotes.
        "SUBSCRIPTION_PAUSED",
    }

    if event_type in active_events:
        plan = _plan_from_entitlements(ent_ids) or "pro"
        until = int(expires_ms / 1000) if expires_ms else None
        with db.connect() as conn:
            conn.execute(
                "UPDATE users SET plan = ?, subscription_until = ? WHERE id = ?",
                (plan, until, user_id),
            )
        print(f"[rc-webhook] -> set plan={plan} until={until} for {user_id}")
    elif event_type == "EXPIRATION":
        with db.connect() as conn:
            conn.execute(
                "UPDATE users SET plan = 'free', subscription_until = NULL WHERE id = ?",
                (user_id,),
            )
        print(f"[rc-webhook] -> demoted to free for {user_id}")
    # else: BILLING_ISSUE, CANCELLATION (intent only), TEST, etc.
    # No mutation needed — entitlement stays active until EXPIRATION.

    return {"ok": True, "event": event_type, "user_id": user_id}
