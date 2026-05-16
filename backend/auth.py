"""Admin auth — env-based HTTP Basic.

Set ADMIN_USER and ADMIN_PASSWORD in the environment to require auth on
admin endpoints. If either is unset, auth is OFF (the original behavior),
so local development doesn't break.

Usage in main.py:

    from .auth import require_admin
    @app.put("/api/config", dependencies=[Depends(require_admin)])
    async def update_config(...): ...

Why not a real auth system: this is a B2B demo for a single operator; an
env-gated basic-auth gate is sufficient to keep accidental visitors out of
a live demo deployment. Production users should put the app behind their
own reverse proxy or SSO.
"""

import os
import secrets
from typing import Optional

from fastapi import HTTPException, Request, status


def _credentials_configured() -> bool:
    return bool(os.environ.get("ADMIN_USER") and os.environ.get("ADMIN_PASSWORD"))


def _parse_basic(header: Optional[str]) -> Optional[tuple]:
    if not header or not header.lower().startswith("basic "):
        return None
    try:
        import base64
        raw = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8", "ignore")
        user, _, pw = raw.partition(":")
        return user, pw
    except Exception:
        return None


def require_admin(request: Request) -> None:
    """Dependency: enforce HTTP Basic when ADMIN_USER + ADMIN_PASSWORD set."""
    if not _credentials_configured():
        return  # Auth disabled for dev convenience.
    expected_user = os.environ.get("ADMIN_USER", "")
    expected_pw = os.environ.get("ADMIN_PASSWORD", "")
    creds = _parse_basic(request.headers.get("authorization"))
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required.",
            headers={"WWW-Authenticate": 'Basic realm="guard-demo-admin"'},
        )
    user, pw = creds
    if not (secrets.compare_digest(user, expected_user) and secrets.compare_digest(pw, expected_pw)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials.",
            headers={"WWW-Authenticate": 'Basic realm="guard-demo-admin"'},
        )


def auth_status() -> dict:
    """For /api/auth/status — does the frontend need to prompt for creds?"""
    return {"enabled": _credentials_configured()}
