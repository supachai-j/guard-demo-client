"""Admin authentication — JWT-based login.

How it works:
- Default credentials come from env (ADMIN_USER + ADMIN_PASSWORD). If unset
  they fall back to `admin` / `admin` (development convenience — a warning
  is logged on startup).
- POST /api/auth/login validates the username + password (bcrypt-compared
  against the stored hash) and returns a JWT bearer token.
- Every admin endpoint depends on `require_admin`, which extracts the token
  from `Authorization: Bearer <token>` and verifies its signature + expiry.
- The JWT signing key is JWT_SECRET from env; if absent, a random key is
  generated at startup (in-memory only — every restart invalidates tokens,
  which is intentional for demos).
- Token lifetime defaults to 12 hours so a demo session never expires
  mid-presentation; tweak ADMIN_TOKEN_TTL_HOURS in env to change.

We deliberately keep this single-user (no DB-backed user table) because
this is a B2B sales demo where the admin is always the operator running
the demo. If a customer needs multi-user RBAC, they can replace this
module with their preferred backend (Auth0, Keycloak, custom).
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Header, HTTPException, status
from jose import JWTError, jwt
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# --- Configuration ---------------------------------------------------------

_DEFAULT_USER = os.environ.get("ADMIN_USER") or "admin"
_DEFAULT_PASSWORD = os.environ.get("ADMIN_PASSWORD") or "admin"
_TOKEN_TTL_HOURS = float(os.environ.get("ADMIN_TOKEN_TTL_HOURS", "12"))
_JWT_ALG = "HS256"
_JWT_SECRET = os.environ.get("JWT_SECRET")

if not _JWT_SECRET:
    # Per-process random secret. Restart invalidates tokens.
    _JWT_SECRET = secrets.token_urlsafe(48)
    logger.warning(
        "JWT_SECRET not set; using a per-process random key (every restart logs admins out). "
        "Set JWT_SECRET in env for stable sessions across restarts."
    )

if _DEFAULT_USER == "admin" and _DEFAULT_PASSWORD == "admin" and not os.environ.get("ADMIN_USER"):
    logger.warning(
        "Admin defaulting to admin / admin — set ADMIN_USER and ADMIN_PASSWORD in env "
        "before exposing this instance to anyone but localhost."
    )


# Pre-hash the password at import time so login comparisons are constant-time.
# bcrypt enforces a 72-byte limit; truncate if a longer password is configured.
_pw_bytes = _DEFAULT_PASSWORD.encode("utf-8")[:72]
_HASHED_PASSWORD = bcrypt.hashpw(_pw_bytes, bcrypt.gensalt())


# --- Schemas ---------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: str


class MeResponse(BaseModel):
    user: str
    expires_at: Optional[datetime] = None


# --- Token helpers ---------------------------------------------------------

def _issue_token(user: str) -> tuple[str, datetime]:
    expires = datetime.utcnow() + timedelta(hours=_TOKEN_TTL_HOURS)
    payload = {
        "sub": user,
        "exp": expires,
        "iat": datetime.utcnow(),
    }
    token = jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALG)
    return token, expires


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALG])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


# --- Login flow ------------------------------------------------------------

def authenticate(username: str, password: str) -> Optional[tuple[str, datetime]]:
    """Validate credentials; return (token, expires_at) on success or None."""
    if not (username and password):
        return None
    # constant-time compare on the username, bcrypt on the password
    if not secrets.compare_digest(username, _DEFAULT_USER):
        return None
    try:
        pw_bytes = password.encode("utf-8")[:72]
        if not bcrypt.checkpw(pw_bytes, _HASHED_PASSWORD):
            return None
    except Exception:
        return None
    return _issue_token(username)


# --- FastAPI dependencies --------------------------------------------------

def require_admin(authorization: Optional[str] = Header(None)) -> str:
    """Dependency: require a valid Bearer token. Returns the username."""
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = _decode_token(token)
    user = claims.get("sub")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def verify_token(token: Optional[str]) -> str:
    """Validate a raw JWT (no `Bearer ` prefix). Returns username or 401s.

    Used by endpoints that can't read the Authorization header — e.g. SSE
    streams consumed via the browser EventSource API, which has no way to
    set custom headers and so authenticates via `?token=` query param.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = _decode_token(token)
    user = claims.get("sub")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def current_user(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """Like require_admin but doesn't 401 — returns None when no/invalid
    token. Used by endpoints that vary their response by auth state
    (e.g. GET /api/config masks API keys for anonymous callers)."""
    token = _extract_bearer(authorization)
    if not token:
        return None
    try:
        return _decode_token(token).get("sub")
    except HTTPException:
        return None


def token_metadata(token: str) -> MeResponse:
    """Used by GET /api/auth/me to report current session info."""
    claims = _decode_token(token)
    exp_ts = claims.get("exp")
    expires_at = datetime.utcfromtimestamp(exp_ts) if isinstance(exp_ts, (int, float)) else None
    return MeResponse(user=claims.get("sub") or "", expires_at=expires_at)


def auth_status() -> dict:
    """For GET /api/auth/status — does the frontend need to show a login?"""
    return {
        "enabled": True,
        "default_user": _DEFAULT_USER,
        "warn_default_password": (
            _DEFAULT_USER == "admin"
            and _DEFAULT_PASSWORD == "admin"
            and not os.environ.get("ADMIN_USER")
        ),
    }
