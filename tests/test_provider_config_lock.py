"""Tests for the demo-safe provider config lock.

When `app_config.provider_config_locked = True`:
- PUT /api/config rejects any change to a provider field (returns 403)
- The lock toggle itself can always be flipped (so the operator can unlock)
- Non-provider fields (theme, system_prompt, webhook_url) remain editable
- Field "edits" that just re-send the existing value are allowed (so the
  existing frontend pattern of "send all fields every save" still works)
"""

from __future__ import annotations

import pytest
from backend import auth as _auth
from backend.database import get_db
from backend.main import app
from backend.models import AppConfig, Base
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture(scope="function")
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(scope="function")
def db_session(engine) -> Session:
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(scope="function")
def seeded_db(db_session: Session):
    cfg = AppConfig(
        id=1,
        openai_api_key="sk-original-key",
        lakera_api_key="lakera-original",
        lakera_project_id="proj-original",
        guardrail_provider="lakera",
        llm_provider="anthropic",
        anthropic_api_key="anth-original",
        openai_model="claude-haiku-4-5",
        system_prompt="Original system prompt",
        theme="blue",
        provider_config_locked=False,
    )
    db_session.add(cfg)
    db_session.commit()
    return db_session


@pytest.fixture
def client(engine, seeded_db):
    SessionLocal = sessionmaker(bind=engine)

    def _override_get_db():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[_auth.require_admin] = lambda: "test-admin"
    app.dependency_overrides[_auth.current_user] = lambda: "test-admin"

    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


# ---------- Lock toggle itself ----------

def test_default_is_unlocked(client: TestClient):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json()["provider_config_locked"] is False


def test_can_engage_lock(client: TestClient, seeded_db: Session):
    resp = client.put("/api/config", json={"provider_config_locked": True})
    assert resp.status_code == 200
    seeded_db.expire_all()
    cfg = seeded_db.query(AppConfig).first()
    assert cfg.provider_config_locked is True


def test_can_unlock_when_locked(client: TestClient, seeded_db: Session):
    """Even when locked, the unlock toggle must always work."""
    cfg = seeded_db.query(AppConfig).first()
    cfg.provider_config_locked = True
    seeded_db.commit()

    resp = client.put("/api/config", json={"provider_config_locked": False})
    assert resp.status_code == 200
    seeded_db.expire_all()
    assert seeded_db.query(AppConfig).first().provider_config_locked is False


# ---------- Provider-field edits while locked ----------

def test_locked_rejects_openai_api_key_change(client: TestClient, seeded_db: Session):
    cfg = seeded_db.query(AppConfig).first()
    cfg.provider_config_locked = True
    seeded_db.commit()

    resp = client.put("/api/config", json={"openai_api_key": "sk-NEW-key-attempt"})
    assert resp.status_code == 403
    assert "locked" in resp.json()["detail"].lower()
    # Stored value unchanged
    seeded_db.expire_all()
    assert seeded_db.query(AppConfig).first().openai_api_key == "sk-original-key"


def test_locked_rejects_lakera_key_change(client: TestClient, seeded_db: Session):
    cfg = seeded_db.query(AppConfig).first()
    cfg.provider_config_locked = True
    seeded_db.commit()

    resp = client.put("/api/config", json={"lakera_api_key": "lakera-NEW-key"})
    assert resp.status_code == 403


def test_locked_rejects_active_provider_change(client: TestClient, seeded_db: Session):
    cfg = seeded_db.query(AppConfig).first()
    cfg.provider_config_locked = True
    seeded_db.commit()

    resp = client.put("/api/config", json={"llm_provider": "openai"})
    assert resp.status_code == 403


def test_locked_rejects_guardrail_provider_change(client: TestClient, seeded_db: Session):
    cfg = seeded_db.query(AppConfig).first()
    cfg.provider_config_locked = True
    seeded_db.commit()

    resp = client.put("/api/config", json={"guardrail_provider": "openai_moderation"})
    assert resp.status_code == 403


def test_locked_error_detail_lists_blocked_fields(client: TestClient, seeded_db: Session):
    cfg = seeded_db.query(AppConfig).first()
    cfg.provider_config_locked = True
    seeded_db.commit()

    resp = client.put("/api/config", json={
        "openai_api_key": "sk-attempt",
        "lakera_api_key": "lakera-attempt",
    })
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    # Operator needs to know which fields blocked them, not just "locked"
    assert "openai_api_key" in detail
    assert "lakera_api_key" in detail


# ---------- Non-provider edits while locked ----------

def test_locked_allows_theme_change(client: TestClient, seeded_db: Session):
    cfg = seeded_db.query(AppConfig).first()
    cfg.provider_config_locked = True
    seeded_db.commit()

    resp = client.put("/api/config", json={"theme": "emerald"})
    assert resp.status_code == 200
    seeded_db.expire_all()
    assert seeded_db.query(AppConfig).first().theme == "emerald"


def test_locked_allows_system_prompt_change(client: TestClient, seeded_db: Session):
    cfg = seeded_db.query(AppConfig).first()
    cfg.provider_config_locked = True
    seeded_db.commit()

    resp = client.put("/api/config", json={"system_prompt": "Updated prompt"})
    assert resp.status_code == 200


def test_locked_allows_webhook_url_change(client: TestClient, seeded_db: Session):
    cfg = seeded_db.query(AppConfig).first()
    cfg.provider_config_locked = True
    seeded_db.commit()

    resp = client.put("/api/config", json={"webhook_url": "https://hooks.slack.com/x"})
    assert resp.status_code == 200


# ---------- Frontend "send all fields" pattern ----------

def test_locked_allows_resend_of_unchanged_provider_fields(client: TestClient, seeded_db: Session):
    """Frontend sends every field on every save. If values match stored, must
    be allowed even when locked (so unrelated edits still go through)."""
    cfg = seeded_db.query(AppConfig).first()
    cfg.provider_config_locked = True
    seeded_db.commit()

    resp = client.put("/api/config", json={
        # All matching stored values
        "openai_api_key": "sk-original-key",
        "lakera_api_key": "lakera-original",
        "lakera_project_id": "proj-original",
        "llm_provider": "anthropic",
        "anthropic_api_key": "anth-original",
        "guardrail_provider": "lakera",
        # Plus a non-provider edit + unlock toggle
        "theme": "purple",
        "provider_config_locked": False,
    })
    assert resp.status_code == 200, resp.text
    seeded_db.expire_all()
    saved = seeded_db.query(AppConfig).first()
    assert saved.theme == "purple"
    assert saved.provider_config_locked is False


def test_locked_blocks_mixed_request_with_one_real_change(client: TestClient, seeded_db: Session):
    """If a payload mixes matching values + ONE actual provider change, block."""
    cfg = seeded_db.query(AppConfig).first()
    cfg.provider_config_locked = True
    seeded_db.commit()

    resp = client.put("/api/config", json={
        "openai_api_key": "sk-original-key",  # unchanged — fine
        "lakera_api_key": "lakera-CHANGED",   # changed — should block
        "llm_provider": "anthropic",           # unchanged — fine
    })
    assert resp.status_code == 403
    assert "lakera_api_key" in resp.json()["detail"]


# ---------- Unlocked baseline (sanity) ----------

def test_unlocked_allows_full_provider_edit(client: TestClient, seeded_db: Session):
    """Lock OFF must not affect normal edits (regression check)."""
    resp = client.put("/api/config", json={
        "openai_api_key": "sk-completely-new",
        "lakera_api_key": "lakera-completely-new",
    })
    assert resp.status_code == 200
