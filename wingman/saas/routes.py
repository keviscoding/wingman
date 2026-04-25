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
    free_lifetime_trial: int = db.FREE_LIFETIME_TRIAL
    free_pro_lifetime_trial: int = db.FREE_PRO_LIFETIME_TRIAL
    free_daily_limit: int = db.FREE_DAILY_LIMIT
    paid_daily_limit: int = db.PAID_DAILY_LIMIT


@router.get("/me", response_model=MeResponse)
async def me(user: Annotated[dict, Depends(current_user)]):
    q = db.get_user_quota_state(user["id"])
    return MeResponse(
        user_id=user["id"],
        email=user["email"],
        display_name=user.get("display_name"),
        plan=user["plan"],
        is_subscribed=q["is_subscribed"],
        subscription_until=q.get("subscription_until"),
        lifetime_used=q["lifetime_used"],
        daily_used=q["daily_used"],
        pro_lifetime_used=q.get("pro_lifetime_used", 0),
        pro_daily_used=q.get("pro_daily_used", 0),
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


@router.post("/quick-capture", response_model=QuickCaptureResponse)
async def quick_capture(
    user: Annotated[dict, Depends(current_user)],
    screenshot: UploadFile = File(...),
    extra_context: str = Form(default=""),
    mode: str = Form(default="fast"),
):
    """Upload a screenshot; receive 5 replies in one HTTP roundtrip.

    `mode` is "fast" (tuned Flash) or "pro" (Gemini 3.1 Pro). Pro is
    paid-only with a small lifetime trial gate for free users.
    """
    if mode not in ("fast", "pro"):
        mode = "fast"

    allowed, reason = db.can_generate(user["id"], mode=mode)
    if not allowed:
        raise HTTPException(status_code=402, detail=reason)

    img_bytes = await screenshot.read()
    if len(img_bytes) > 10 * 1024 * 1024:  # 10 MB cap
        raise HTTPException(status_code=413, detail="image_too_large")

    ctx = get_context(user["id"], plan=user.get("plan", "free"))

    from .pipeline import quick_capture_for_user
    try:
        result = await quick_capture_for_user(
            ctx, img_bytes, extra_context=extra_context, mode=mode,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="generation_failed") from exc

    if not result.get("replies"):
        raise HTTPException(status_code=502, detail="no_replies_produced")

    db.record_generation(
        user_id=user["id"],
        model=result.get("model", "unknown"),
        cost_cents=result.get("cost_cents", 0),
        reply_count=len(result["replies"]),
        mode=mode,
    )

    return QuickCaptureResponse(
        chat_id=result["chat_id"],
        contact=result["contact"],
        transcript=result["transcript"],
        replies=[ReplyOption(**r) for r in result["replies"]],
        read=result.get("read", ""),
        advice=result.get("advice", ""),
        generated_at=int(time.time()),
        model=result.get("model", "tuned-v4"),
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
    return result


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
