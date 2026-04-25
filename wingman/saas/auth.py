"""Auth: password hashing + JWT issue/verify.

Mobile clients hold a single access token (24h life) — refresh flow can
come later. JWTs are signed with HS256 using JWT_SECRET from env. In
prod, set this to a long random string and rotate periodically.

Email + password is the MVP. Apple Sign In + Google Sign In can plug in
later as additional ``/auth/apple`` and ``/auth/google`` endpoints that
also issue our JWTs once they verify the provider's identity token.
"""

from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt, JWTError

from . import db

JWT_SECRET = os.getenv("WINGMAN_JWT_SECRET", "").strip()
if not JWT_SECRET:
    # Auto-generate one for dev and persist it so restarts don't
    # invalidate every active session.
    secret_path = "data/saas/.jwt_secret"
    try:
        with open(secret_path) as f:
            JWT_SECRET = f.read().strip()
    except FileNotFoundError:
        JWT_SECRET = secrets.token_urlsafe(48)
        os.makedirs("data/saas", exist_ok=True)
        with open(secret_path, "w") as f:
            f.write(JWT_SECRET)

JWT_ALGO = "HS256"
JWT_EXPIRE_HOURS = 24 * 30  # 30 days — mobile-friendly, low friction


def _truncate_for_bcrypt(plain: str) -> bytes:
    """bcrypt has a 72-byte limit on the password input. Truncate
    AFTER encoding so multibyte chars aren't sliced mid-codepoint."""
    return plain.encode("utf-8")[:72]


def hash_password(plain: str) -> str:
    """Returns the bcrypt hash as ASCII string for DB storage."""
    pw = _truncate_for_bcrypt(plain)
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_truncate_for_bcrypt(plain), hashed.encode("ascii"))
    except Exception:
        return False


def issue_token(user_id: str) -> tuple[str, int]:
    """Returns (jwt, expires_at_epoch_seconds)."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": secrets.token_urlsafe(12),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    return token, int(exp.timestamp())


def verify_token(token: str) -> dict | None:
    """Returns the payload dict if valid, None otherwise."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return payload
    except JWTError:
        return None


def authenticate(email: str, password: str) -> dict | None:
    """Returns the user dict on success, None otherwise."""
    user = db.get_user_by_email(email)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user
