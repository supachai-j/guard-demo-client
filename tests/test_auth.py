"""Tests for backend.auth — JWT issue/verify, login, require_admin dep."""

from datetime import datetime, timedelta

import pytest
from backend import auth as auth_mod
from fastapi import HTTPException

# ---------- _issue_token / _decode_token ----------------------------------

def test_issue_token_round_trips_through_decode():
    token, expires = auth_mod._issue_token("alice")
    claims = auth_mod._decode_token(token)
    assert claims["sub"] == "alice"
    # expires is reasonably in the future (TTL-driven; allow ±2s skew)
    assert (expires - datetime.utcnow()).total_seconds() > 60


def test_decode_token_rejects_garbage():
    with pytest.raises(HTTPException) as exc:
        auth_mod._decode_token("not.a.jwt")
    assert exc.value.status_code == 401


def test_decode_token_rejects_expired_token():
    # Build a token with exp in the past
    from jose import jwt
    payload = {
        "sub": "expired",
        "exp": datetime.utcnow() - timedelta(hours=1),
        "iat": datetime.utcnow() - timedelta(hours=2),
    }
    stale = jwt.encode(payload, auth_mod._JWT_SECRET, algorithm=auth_mod._JWT_ALG)
    with pytest.raises(HTTPException) as exc:
        auth_mod._decode_token(stale)
    assert exc.value.status_code == 401


# ---------- verify_token (the query-param SSE auth helper) ----------------

def test_verify_token_returns_subject():
    token, _ = auth_mod._issue_token("bob")
    assert auth_mod.verify_token(token) == "bob"


def test_verify_token_401_on_empty():
    for bad in (None, "", "   "):
        with pytest.raises(HTTPException) as exc:
            auth_mod.verify_token(bad)
        assert exc.value.status_code == 401


def test_verify_token_401_on_token_missing_sub():
    """A token signed with the right key but missing `sub` must still 401."""
    from jose import jwt
    payload = {"exp": datetime.utcnow() + timedelta(hours=1)}
    nosub = jwt.encode(payload, auth_mod._JWT_SECRET, algorithm=auth_mod._JWT_ALG)
    with pytest.raises(HTTPException) as exc:
        auth_mod.verify_token(nosub)
    assert exc.value.status_code == 401


# ---------- authenticate (login) ------------------------------------------

def test_authenticate_succeeds_with_default_creds():
    # conftest doesn't override ADMIN_USER/ADMIN_PASSWORD, so default is admin/admin.
    result = auth_mod.authenticate("admin", "admin")
    assert result is not None
    token, expires = result
    assert isinstance(token, str) and token
    assert auth_mod._decode_token(token)["sub"] == "admin"


def test_authenticate_fails_on_wrong_password():
    assert auth_mod.authenticate("admin", "wrong-password") is None


def test_authenticate_fails_on_wrong_user():
    assert auth_mod.authenticate("not-admin", "admin") is None


def test_authenticate_fails_on_empty():
    assert auth_mod.authenticate("", "") is None
    assert auth_mod.authenticate("admin", "") is None
    assert auth_mod.authenticate("", "admin") is None


# ---------- require_admin dependency --------------------------------------

def test_require_admin_accepts_valid_bearer():
    token, _ = auth_mod._issue_token("admin")
    assert auth_mod.require_admin(authorization=f"Bearer {token}") == "admin"


def test_require_admin_rejects_missing_header():
    with pytest.raises(HTTPException) as exc:
        auth_mod.require_admin(authorization=None)
    assert exc.value.status_code == 401


def test_require_admin_rejects_wrong_scheme():
    token, _ = auth_mod._issue_token("admin")
    with pytest.raises(HTTPException) as exc:
        auth_mod.require_admin(authorization=f"Basic {token}")
    assert exc.value.status_code == 401


# ---------- current_user (non-401 variant) --------------------------------

def test_current_user_returns_none_when_unauthenticated():
    assert auth_mod.current_user(authorization=None) is None
    assert auth_mod.current_user(authorization="Bearer garbage") is None


def test_current_user_returns_subject_when_valid():
    token, _ = auth_mod._issue_token("alice")
    assert auth_mod.current_user(authorization=f"Bearer {token}") == "alice"


# ---------- auth_status ---------------------------------------------------

def test_auth_status_shape():
    s = auth_mod.auth_status()
    assert s["enabled"] is True
    assert "default_user" in s
    assert "warn_default_password" in s
