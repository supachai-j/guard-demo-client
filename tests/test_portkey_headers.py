"""Tests for Portkey gateway headers in backend.llm_client.

Covers the new Config / Metadata orchestration headers (x-portkey-config,
x-portkey-metadata) plus the header-safe JSON helper that backs them.

Scope: these assert the kwargs/headers dict is assembled correctly. They do
NOT prove litellm forwards extra_headers to Portkey or that Portkey accepts
the values — that needs a live key + request.
"""

from types import SimpleNamespace

from backend.llm_client import (
    _build_litellm_kwargs,
    _portkey_guardrail_block_status,
    _portkey_header_value,
)


def _cfg(**fields):
    """Minimal AppConfig stand-in. Dispatch reads every attr via getattr()."""
    base = {
        "llm_provider": "portkey",
        "portkey_api_key": "pk-test",
        "portkey_virtual_key": None,
        "portkey_base_url": None,
        "portkey_config": None,
        "portkey_metadata": None,
    }
    base.update(fields)
    return SimpleNamespace(**base)


def _portkey_kwargs(**fields):
    return _build_litellm_kwargs(
        _cfg(**fields),
        model="gpt-4o",
        temperature=0.7,
        messages=[{"role": "user", "content": "hi"}],
    )


# ---------- _portkey_header_value (pure helper) --------------------------

def test_header_value_empty_returns_none():
    assert _portkey_header_value(None) is None
    assert _portkey_header_value("") is None
    assert _portkey_header_value("   ") is None


def test_header_value_slug_passthrough_trimmed():
    assert _portkey_header_value("  pc-abc123  ") == "pc-abc123"


def test_header_value_json_is_compacted():
    # Whitespace/newlines that could corrupt a header are stripped out.
    assert _portkey_header_value('{ "_user": "demo",\n "tier": 2 }') == '{"_user":"demo","tier":2}'


def test_header_value_invalid_json_passes_through():
    # A non-JSON string (typo or bare slug) is sent verbatim for the gateway to judge.
    assert _portkey_header_value("{not json") == "{not json"


# ---------- dispatch header assembly -------------------------------------

def test_base_portkey_headers_present():
    kwargs = _portkey_kwargs(portkey_virtual_key="vk-1")
    headers = kwargs["extra_headers"]
    assert headers["x-portkey-api-key"] == "pk-test"
    assert headers["x-portkey-virtual-key"] == "vk-1"
    assert kwargs["custom_llm_provider"] == "openai"


def test_config_and_metadata_headers_set_when_configured():
    kwargs = _portkey_kwargs(
        portkey_config="pc-fallbacks",
        portkey_metadata='{"_user": "demo"}',
    )
    headers = kwargs["extra_headers"]
    assert headers["x-portkey-config"] == "pc-fallbacks"
    assert headers["x-portkey-metadata"] == '{"_user":"demo"}'


def test_config_and_metadata_headers_absent_when_unset():
    headers = _portkey_kwargs()["extra_headers"]
    assert "x-portkey-config" not in headers
    assert "x-portkey-metadata" not in headers


# ---------- gateway-guardrail block detection (HTTP 446) -----------------

def test_guardrail_block_status_detected_from_446_message():
    err = Exception(
        "litellm.APIError: APIError: OpenAIException - The guardrail checks "
        "defined in the config failed. You can find more information in the "
        "`hook_results` object."
    )
    status = _portkey_guardrail_block_status(err)
    assert status is not None
    assert status["flagged"] is True
    assert status["breakdown"][0]["detected"] is True
    assert status["metadata"]["source"] == "portkey_gateway"


def test_guardrail_block_status_none_for_unrelated_error():
    assert _portkey_guardrail_block_status(Exception("rate limit exceeded")) is None
    assert _portkey_guardrail_block_status(Exception("Invalid config id passed")) is None
