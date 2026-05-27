"""Tests for backend.llm_capabilities — the per-model vision gate.

Locks the deny-list semantics so future additions don't accidentally
re-enable image requests against models that produce opaque gateway
errors when handed OpenAI-style vision content blocks.
"""
from __future__ import annotations

import pytest
from backend import llm_capabilities


class TestIsKnownTextOnly:
    def test_thaillm_id_is_text_only(self):
        # The model id that surfaced the original bug: ThaiLLM gateway
        # returned "request body must be valid JSON" on image requests.
        assert llm_capabilities.is_known_text_only("OpenThaiGPT-ThaiLLM-8B-Instruct-v7.2") is True

    def test_match_is_case_insensitive(self):
        assert llm_capabilities.is_known_text_only("THAILLM-7B") is True
        assert llm_capabilities.is_known_text_only("openthaigpt-base") is True

    @pytest.mark.parametrize("model_id", [
        "gpt-4o",
        "gpt-4o-mini",
        "claude-3-opus",
        "claude-opus-4-7",
        "gemini-1.5-pro",
        "mistral-large",
        "llama-3.2-90b",
    ])
    def test_known_vision_or_unlisted_passes(self, model_id):
        # Conservative default: anything not in _KNOWN_TEXT_ONLY returns
        # False so the route handler lets it through. The provider can
        # then speak for itself if it doesn't actually support vision.
        assert llm_capabilities.is_known_text_only(model_id) is False

    def test_empty_or_none_returns_false(self):
        assert llm_capabilities.is_known_text_only("") is False
        assert llm_capabilities.is_known_text_only(None) is False


class TestRejectImageRequestMessage:
    def test_mentions_the_model_id_so_operator_knows_what_to_swap(self):
        msg = llm_capabilities.reject_image_request_message("OpenThaiGPT-ThaiLLM-8B-Instruct-v7.2")
        assert "OpenThaiGPT-ThaiLLM-8B-Instruct-v7.2" in msg

    def test_suggests_at_least_one_vision_capable_alternative(self):
        # The whole point of the message is that the operator can act on
        # it without leaving the chat. Naming concrete alternatives is
        # the actionable part — don't ever drop this.
        msg = llm_capabilities.reject_image_request_message("thaillm").lower()
        assert any(s in msg for s in ("gpt-4o", "claude", "gemini")), msg

    def test_points_at_admin_llm_tab(self):
        # Where to flip the active model. Without this the operator has
        # to go hunt for it.
        msg = llm_capabilities.reject_image_request_message("thaillm").lower()
        assert "admin" in msg and "llm" in msg


# ---------- vision allow-list ---------------------------------------------

class TestIsKnownVisionCapable:
    @pytest.mark.parametrize("model_id", [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4-vision-preview",
        "claude-3-opus",
        "claude-3-haiku-20240307",
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        "gemini-2.0-flash-exp",
        "pixtral-12b",
    ])
    def test_confirmed_vision_models(self, model_id):
        assert llm_capabilities.is_known_vision_capable(model_id) is True

    @pytest.mark.parametrize("model_id", [
        "gpt-3.5-turbo",        # Old OpenAI, text-only
        "thaillm-7b",            # Confirmed text-only (deny-list)
        "llama-3.2-70b",         # Base llama, no vision
        "mistral-large",         # Mistral text-only model
        "random-unknown-model",  # Unknown — must default to False
    ])
    def test_non_vision_or_unknown_returns_false(self, model_id):
        # Conservative: anything not in the allow-list returns False so
        # the OCR resolver picks something more reliable from the
        # fallback chain instead of betting on guesswork.
        assert llm_capabilities.is_known_vision_capable(model_id) is False

    def test_empty_or_none_returns_false(self):
        assert llm_capabilities.is_known_vision_capable("") is False
        assert llm_capabilities.is_known_vision_capable(None) is False


# ---------- smart fallback chain ------------------------------------------

class _FakeCfg:
    """Minimal cfg shape — only the attrs the resolver reads."""
    def __init__(self, **kwargs):
        self.openai_api_key = None
        self.google_api_key = None
        self.anthropic_api_key = None
        self.openai_model = None
        self.ocr_model = None
        self.disabled_providers = []
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestSmartOcrFallback:
    def test_no_keys_returns_none(self):
        assert llm_capabilities.smart_ocr_fallback(_FakeCfg()) is None

    def test_openai_first_in_chain(self):
        # All three keys configured — chain should pick OpenAI first
        # (cheapest + fastest vision option).
        cfg = _FakeCfg(
            openai_api_key="sk-fake",
            google_api_key="g-fake",
            anthropic_api_key="ak-fake",
        )
        assert llm_capabilities.smart_ocr_fallback(cfg) == "gpt-4o-mini"

    def test_skips_to_google_when_openai_missing(self):
        cfg = _FakeCfg(google_api_key="g-fake", anthropic_api_key="ak-fake")
        assert llm_capabilities.smart_ocr_fallback(cfg) == "gemini-1.5-flash"

    def test_falls_through_to_anthropic_last(self):
        cfg = _FakeCfg(anthropic_api_key="ak-fake")
        assert llm_capabilities.smart_ocr_fallback(cfg) == "claude-3-haiku-20240307"

    def test_skips_disabled_provider_even_with_key(self):
        # Operator disabled OpenAI from the Providers tab; fallback
        # should respect that and try Google next even though the
        # OpenAI key is still saved.
        cfg = _FakeCfg(
            openai_api_key="sk-fake",
            google_api_key="g-fake",
            disabled_providers=["openai"],
        )
        assert llm_capabilities.smart_ocr_fallback(cfg) == "gemini-1.5-flash"

    def test_all_providers_disabled_returns_none(self):
        cfg = _FakeCfg(
            openai_api_key="sk-fake",
            google_api_key="g-fake",
            anthropic_api_key="ak-fake",
            disabled_providers=["openai", "google", "anthropic"],
        )
        assert llm_capabilities.smart_ocr_fallback(cfg) is None


# ---------- resolve_ocr_model — the orchestrator -------------------------

class TestResolveOcrModel:
    def test_explicit_override_wins(self):
        # cfg.ocr_model takes priority even when it's an unknown id —
        # operator is trusted to know what they're doing.
        cfg = _FakeCfg(
            ocr_model="some-custom-vision-model",
            openai_model="gpt-4o",   # active is also vision-capable
            openai_api_key="sk-fake",
        )
        model, source = llm_capabilities.resolve_ocr_model(cfg)
        assert model == "some-custom-vision-model"
        assert source == "explicit"

    def test_active_llm_used_when_vision_capable(self):
        cfg = _FakeCfg(openai_model="gpt-4o", openai_api_key="sk-fake")
        model, source = llm_capabilities.resolve_ocr_model(cfg)
        assert model == "gpt-4o"
        assert source == "active"

    def test_falls_back_when_active_is_text_only(self):
        # Reproduces the real-world bug: ThaiLLM active, image attached,
        # OCR needs to use a vision model from the fallback chain instead.
        cfg = _FakeCfg(
            openai_model="OpenThaiGPT-ThaiLLM-8B-Instruct-v7.2",
            openai_api_key="sk-fake",   # OpenAI key available for fallback
        )
        model, source = llm_capabilities.resolve_ocr_model(cfg)
        assert model == "gpt-4o-mini"
        assert source == "fallback"

    def test_falls_back_when_active_is_unknown(self):
        # Conservative: unknown active model → don't bet on it, use the
        # confirmed-vision fallback chain. Better one extra cheap call
        # than a silent guardrail bypass.
        cfg = _FakeCfg(
            openai_model="some-random-fine-tune-v3",
            google_api_key="g-fake",
        )
        model, source = llm_capabilities.resolve_ocr_model(cfg)
        assert model == "gemini-1.5-flash"
        assert source == "fallback"

    def test_returns_none_when_no_path_works(self):
        # Active text-only, no fallback keys configured. Source="none"
        # tells the caller to log + degrade gracefully.
        cfg = _FakeCfg(openai_model="thaillm-7b")
        model, source = llm_capabilities.resolve_ocr_model(cfg)
        assert model is None
        assert source == "none"

    def test_explicit_override_beats_disabled_provider_fallback(self):
        # Even if every fallback provider is disabled, the explicit
        # override is still used — operator's call to make.
        cfg = _FakeCfg(
            ocr_model="my-preferred-vision-model",
            openai_model="thaillm-7b",
            openai_api_key="sk-fake",
            disabled_providers=["openai", "google", "anthropic"],
        )
        model, source = llm_capabilities.resolve_ocr_model(cfg)
        assert model == "my-preferred-vision-model"
        assert source == "explicit"
