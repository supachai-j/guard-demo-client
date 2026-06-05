"""Tests for the Portkey gateway-guardrails adapter.

Fixtures mirror hook_results shapes observed against the live Portkey gateway
(deny -> HTTP 446 + hook verdict:false; allow -> 200 + verdict:true; the AIRS
integration returning 403 inside a check), so the mapping is pinned to real
behaviour rather than assumed verdict polarity.
"""

from types import SimpleNamespace

from backend.guardrail_provider.portkey_provider import (
    PortkeyGuardrailProvider,
    _map_hook_results,
)

SRC = "portkey_guardrail"


def _hook(verdict, checks):
    return {"id": "pg-test-0001", "verdict": verdict, "checks": checks}


# ---------- is_configured ----------------------------------------------------

def test_is_configured_requires_key_and_config():
    assert PortkeyGuardrailProvider.is_configured(SimpleNamespace(portkey_api_key="pk", portkey_config="pc-x")) is True
    assert PortkeyGuardrailProvider.is_configured(SimpleNamespace(portkey_api_key="pk", portkey_config=None)) is False
    assert PortkeyGuardrailProvider.is_configured(SimpleNamespace(portkey_api_key=None, portkey_config="pc-x")) is False


# ---------- _map_hook_results (observed shapes) ------------------------------

def test_deny_446_is_flagged():
    body = {"error": {"message": "guardrail checks failed"},
            "hook_results": {"before_request_hooks": [_hook(False, [{"id": "default.contains", "verdict": False}])]}}
    st = _map_hook_results(446, body, SRC)
    assert st["flagged"] is True
    assert st["breakdown"] and st["breakdown"][0]["detected"] is True


def test_allow_200_not_flagged():
    body = {"choices": [{"message": {"content": "x"}}],
            "hook_results": {"before_request_hooks": [_hook(True, [{"id": "default.contains", "verdict": True}])]}}
    st = _map_hook_results(200, body, SRC)
    assert st["flagged"] is False
    assert st["breakdown"] == []


def test_monitor_mode_verdict_false_flags_without_446():
    # deny:false/async -> request returns 200 but the hook still reports a fail.
    body = {"choices": [{"message": {"content": "x"}}],
            "hook_results": {"before_request_hooks": [_hook(False, [{"id": "x", "verdict": False}])]}}
    st = _map_hook_results(200, body, SRC)
    assert st["flagged"] is True


def test_errored_check_becomes_auth_failed_not_passed():
    # The AIRS integration 403s inside the check -> it never evaluated.
    body = {"choices": [{"message": {"content": "x"}}],
            "hook_results": {"before_request_hooks": [
                {"id": "pg-prisma-c06001", "verdict": True,
                 "checks": [{"id": "panw-prisma-airs.intercept", "verdict": False,
                             "error": {"name": "HttpError", "message": "HTTP error! status: 403"},
                             "fail_on_error": False}]}]}}
    st = _map_hook_results(200, body, SRC)
    assert st["flagged"] is False
    assert st["metadata"]["error"] == "auth_failed"


def test_no_guardrails_in_config_is_clean_note():
    body = {"choices": [{"message": {"content": "x"}}]}
    st = _map_hook_results(200, body, SRC)
    assert st["flagged"] is False
    assert "no guardrails" in st["metadata"].get("note", "")


def test_gateway_error_without_hooks_is_error_status():
    body = {"error": {"message": "Invalid config passed"}}
    st = _map_hook_results(400, body, SRC)
    assert st["flagged"] is False
    assert st["metadata"]["error"] in ("http_error", "auth_failed")
    assert st["metadata"]["http_status"] == 400
