"""Tests for the disabled_providers list — operator can hide individual
providers from runtime fan-out + the active selector.

Separate from "configured" (has key): a provider can be configured but
disabled (e.g. OpenAI Moderation when daily quota is exhausted).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend import auth as _auth
from backend.database import get_db
from backend.main import app
from backend.models import AppConfig, Base, Playbook


@pytest.fixture(scope="function")
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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
        openai_api_key="sk-x",
        lakera_api_key="lakera-x",
        lakera_project_id="proj-x",
        llm_provider="anthropic",
        anthropic_api_key="anth-x",
        guardrail_provider="lakera",
        openai_model="claude-haiku-4-5",
        provider_config_locked=False,
        disabled_providers=[],
    )
    db_session.add(cfg)
    db_session.add(Playbook(
        slug="pb_basic",
        name="Basic PB",
        prompts=[{"id": "T1", "category": "Test", "prompt": "block me", "expected": "blocked"}],
    ))
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


# ---------- defaults ----------

def test_default_disabled_list_is_empty(client: TestClient):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json()["disabled_providers"] == []


def test_providers_endpoint_exposes_enabled_true_by_default(client: TestClient):
    resp = client.get("/api/providers")
    assert resp.status_code == 200
    for p in resp.json()["providers"]:
        assert p["enabled"] is True, f"{p['id']} should be enabled by default"


def test_guardrail_providers_endpoint_exposes_enabled_true_by_default(client: TestClient):
    resp = client.get("/api/guardrail-providers")
    for p in resp.json()["providers"]:
        assert p["enabled"] is True, f"{p['id']} should be enabled by default"


# ---------- toggle disabled ----------

def test_disable_a_provider(client: TestClient, seeded_db: Session):
    resp = client.put("/api/config", json={"disabled_providers": ["openai_moderation"]})
    assert resp.status_code == 200, resp.text
    # GET /api/guardrail-providers reflects it
    listing = client.get("/api/guardrail-providers").json()["providers"]
    oai = next(p for p in listing if p["id"] == "openai_moderation")
    assert oai["enabled"] is False
    # Other providers still enabled
    lk = next(p for p in listing if p["id"] == "lakera")
    assert lk["enabled"] is True


def test_round_trip_enable_disable(client: TestClient):
    client.put("/api/config", json={"disabled_providers": ["mistral"]})
    listing = client.get("/api/providers").json()["providers"]
    assert next(p for p in listing if p["id"] == "mistral")["enabled"] is False
    client.put("/api/config", json={"disabled_providers": []})
    listing = client.get("/api/providers").json()["providers"]
    assert next(p for p in listing if p["id"] == "mistral")["enabled"] is True


# ---------- can't activate a disabled provider ----------

def test_cannot_set_disabled_llm_provider_as_active(client: TestClient):
    client.put("/api/config", json={"disabled_providers": ["openai"]})
    resp = client.put("/api/config", json={"llm_provider": "openai"})
    assert resp.status_code == 400
    assert "disabled" in resp.json()["detail"].lower()


def test_cannot_set_disabled_guardrail_provider_as_active(client: TestClient):
    client.put("/api/config", json={"disabled_providers": ["openai_moderation"]})
    resp = client.put("/api/config", json={"guardrail_provider": "openai_moderation"})
    assert resp.status_code == 400


def test_cannot_disable_the_currently_active_provider_without_swapping(client: TestClient):
    """If user tries to add the active provider to disabled list without
    flipping active first, reject. Prevents silent state where active points
    at a disabled provider."""
    # llm_provider = "anthropic" (from seeded_db)
    resp = client.put("/api/config", json={"disabled_providers": ["anthropic"]})
    assert resp.status_code == 400
    assert "anthropic" in resp.json()["detail"].lower()


def test_can_disable_active_provider_when_also_swapping_active(client: TestClient):
    """Atomic: disable previous active + activate something else in same request."""
    resp = client.put("/api/config", json={
        "disabled_providers": ["anthropic"],
        "llm_provider": "openai",
    })
    assert resp.status_code == 200


# ---------- lock interaction ----------

def test_lock_blocks_disabled_providers_changes(client: TestClient, seeded_db: Session):
    """disabled_providers is in PROVIDER_CONFIG_FIELDS so lock applies."""
    cfg = seeded_db.query(AppConfig).first()
    cfg.provider_config_locked = True
    seeded_db.commit()
    resp = client.put("/api/config", json={"disabled_providers": ["openai"]})
    assert resp.status_code == 403


# ---------- runtime: matrix rejects disabled with clear error ----------

def test_matrix_endpoint_rejects_disabled_provider(client: TestClient):
    """User explicitly picks a disabled provider in matrix → error entry
    rather than silent skip."""
    client.put("/api/config", json={"disabled_providers": ["openai_moderation"]})
    resp = client.post("/api/playbook-runs/matrix", json={
        "playbook_ids": ["pb_basic"],
        "provider_ids": ["openai_moderation"],
    })
    assert resp.status_code == 200
    body = resp.json()
    pb = body["playbooks"][0]
    assert pb["runs"] == []
    assert len(pb["errors"]) == 1
    assert "disabled" in pb["errors"][0]["error"].lower()
