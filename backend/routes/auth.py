"""Admin authentication routes. The login screen at /login (frontend)
hits these — there's no DB-backed user table; auth is a single
environment-configured account whose token is signed with JWT_SECRET.
See backend/auth.py for the actual credential check."""

from fastapi import APIRouter, Depends, HTTPException

from .. import auth as _auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
async def get_auth_status():
    """Public — frontend uses this to decide whether to show the login screen."""
    return _auth.auth_status()


@router.post("/login", response_model=_auth.LoginResponse)
async def login(body: _auth.LoginRequest):
    """Validate credentials and return a JWT bearer token."""
    result = _auth.authenticate(body.username, body.password)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    token, expires = result
    return _auth.LoginResponse(access_token=token, token_type="bearer", expires_at=expires, user=body.username)


@router.get("/me", response_model=_auth.MeResponse)
async def me(user: str = Depends(_auth.require_admin)):
    """Return the current authenticated user. 401 when no/expired token."""
    return _auth.MeResponse(user=user)


@router.post("/logout")
async def logout(user: str = Depends(_auth.require_admin)):
    """JWT is stateless — logout is a client-side concern (drop the token).
    Endpoint exists so the UI can confirm the call succeeded."""
    return {"logged_out": True, "user": user}
