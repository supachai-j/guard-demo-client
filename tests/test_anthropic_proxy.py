"""Tests for the Anthropic-format gateway shim (Claude for Office bridge).

The forward-to-Portkey path needs the network, so these focus on the local
gates: the enable flag and the x-api-key validation (the security boundary
that keeps this from being an open relay).
"""


from backend.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_disabled_flag_returns_404(monkeypatch):
    monkeypatch.setenv("CLAUDE_OFFICE_PROXY_ENABLED", "0")
    r = client.post("/v1/messages", headers={"x-api-key": "whatever"}, json={"messages": []})
    assert r.status_code == 404


def test_missing_key_rejected(monkeypatch):
    monkeypatch.setenv("CLAUDE_OFFICE_PROXY_ENABLED", "1")
    r = client.post("/v1/messages", json={"messages": []})
    # Either no Portkey configured (503) or key required (401) — never a forward.
    assert r.status_code in (401, 503)
    body = r.json()
    assert body["type"] == "error"


def test_wrong_key_rejected(monkeypatch):
    monkeypatch.setenv("CLAUDE_OFFICE_PROXY_ENABLED", "1")
    r = client.post("/v1/messages", headers={"x-api-key": "definitely-not-the-portkey-key"},
                    json={"messages": [{"role": "user", "content": "hi"}]})
    # 401 when a Portkey key is set (mismatch), 503 when none is configured.
    assert r.status_code in (401, 503)
    assert r.json()["type"] == "error"


def test_enabled_by_default(monkeypatch):
    monkeypatch.delenv("CLAUDE_OFFICE_PROXY_ENABLED", raising=False)
    # With the flag unset the route is live, so a keyless call is gated by auth
    # (401/503), not hidden (404).
    r = client.post("/v1/messages", json={"messages": []})
    assert r.status_code in (401, 503)
