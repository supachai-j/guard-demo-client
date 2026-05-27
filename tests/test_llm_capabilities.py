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
