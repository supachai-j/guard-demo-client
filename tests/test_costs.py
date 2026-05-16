"""Tests for backend.costs — pricing lookups, USD math, token extraction."""

import math

from backend.costs import (
    PRICING,
    estimate_cost_usd,
    extract_token_usage,
    get_price,
)

# ---------- get_price ----------------------------------------------------

def test_get_price_returns_tuple_for_known_model():
    price = get_price("openai", "gpt-4o")
    assert price is not None
    pin, pout = price
    assert pin > 0 and pout > 0
    assert pout >= pin  # output tokens always at least input price


def test_get_price_returns_none_for_unknown_model():
    assert get_price("openai", "gpt-quantum-99") is None


def test_get_price_returns_none_for_unknown_provider():
    assert get_price("not-a-provider", "any-model") is None


def test_get_price_returns_none_for_empty_inputs():
    assert get_price("", "") is None


# ---------- estimate_cost_usd -------------------------------------------

def test_estimate_cost_usd_math():
    """gpt-4o is $2.50/M input, $10.00/M output → 1000 in + 500 out = $0.0075."""
    cost = estimate_cost_usd("openai", "gpt-4o", input_tokens=1000, output_tokens=500)
    assert cost is not None
    assert math.isclose(cost, 0.0075, abs_tol=1e-6)


def test_estimate_cost_usd_zero_tokens_returns_zero():
    cost = estimate_cost_usd("openai", "gpt-4o", input_tokens=0, output_tokens=0)
    assert cost == 0.0


def test_estimate_cost_usd_ollama_always_zero():
    """Local Ollama costs $0 regardless of model — return 0.0, not None."""
    assert estimate_cost_usd("ollama", "llama3", input_tokens=10000, output_tokens=10000) == 0.0


def test_estimate_cost_usd_unknown_proxy_routing_returns_none():
    """Gateway providers (LiteLLM proxy, Portkey, OpenRouter) bill via the
    upstream route — when the model isn't in our pricing table we should
    return None ('unknown') so the UI can show a clear marker."""
    for provider in ("litellm_proxy", "portkey", "openrouter"):
        assert (
            estimate_cost_usd(provider, "some-arbitrary-model", 100, 100) is None
        ), f"{provider} should return None for unknown routed model"


def test_estimate_cost_usd_none_for_unknown_provider():
    assert estimate_cost_usd("not-a-provider", "anything", 100, 100) is None


def test_estimate_cost_usd_returns_none_for_missing_pricing():
    """Some provider entries are intentionally empty (e.g. openrouter)."""
    # Even with valid provider + tokens, returns None when no pricing row matches.
    assert estimate_cost_usd("openrouter", "openai/gpt-4o", 100, 100) is None


# ---------- extract_token_usage -----------------------------------------

def test_extract_token_usage_openai_shape():
    resp = {"usage": {"prompt_tokens": 120, "completion_tokens": 45}}
    assert extract_token_usage(resp) == (120, 45)


def test_extract_token_usage_handles_alt_keys():
    """Some providers emit input_tokens / output_tokens instead."""
    resp = {"usage": {"input_tokens": 80, "output_tokens": 30}}
    assert extract_token_usage(resp) == (80, 30)


def test_extract_token_usage_zeros_when_missing():
    assert extract_token_usage({}) == (0, 0)
    assert extract_token_usage({"usage": {}}) == (0, 0)


def test_extract_token_usage_never_raises_on_garbage():
    assert extract_token_usage({"usage": "not-a-dict"}) == (0, 0)
    # Non-int values default to 0 rather than crashing
    resp = {"usage": {"prompt_tokens": "??", "completion_tokens": None}}
    assert extract_token_usage(resp) == (0, 0)


# ---------- pricing-table integrity --------------------------------------

def test_every_provider_in_PROVIDERS_has_pricing_entry():
    """Catch the mistake we made when adding OpenRouter without a pricing entry."""
    from backend.providers import PROVIDERS as P
    for pid in P:
        assert pid in PRICING, f"provider {pid!r} missing from costs.PRICING"
