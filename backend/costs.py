"""LLM pricing table + cost calculator.

Prices are approximate USD per 1M tokens (input / output) as of 2026-Q2. They're
intentionally hard-coded here rather than fetched live because (a) most demo
audiences only need order-of-magnitude accuracy and (b) every vendor has its
own pricing page format. Update this table when prices change.

Sources: vendor pricing pages (OpenAI/Anthropic/Google/Mistral/Groq/Together).
"""

from typing import Any, Dict, Optional, Tuple

# Provider -> { model_id -> (input_price_per_1m, output_price_per_1m) }
# Prices in USD per million tokens.
PRICING: Dict[str, Dict[str, Tuple[float, float]]] = {
    "openai": {
        "gpt-5":          (5.00,  15.00),
        "gpt-5-mini":     (0.50,   2.00),
        "gpt-5-nano":     (0.10,   0.40),
        "gpt-4o":         (2.50,  10.00),
        "gpt-4o-mini":    (0.15,   0.60),
        "gpt-4-turbo":    (10.00, 30.00),
        "gpt-4":          (30.00, 60.00),
        "gpt-3.5-turbo":  (0.50,   1.50),
    },
    "anthropic": {
        # Claude 4.x family (current). Old 3.x snapshots removed because
        # Anthropic returns 404 for them in early 2026.
        # Prices are approximate USD per 1M tokens — update from the official
        # pricing page when shipping a release.
        "claude-opus-4-7":             (15.00, 75.00),
        "claude-sonnet-4-6":           (3.00,  15.00),
        "claude-haiku-4-5-20251001":   (0.80,   4.00),
    },
    "google": {
        "gemini-2.0-flash-exp":  (0.00,  0.00),  # experimental, free tier
        "gemini-1.5-pro":        (1.25,  5.00),
        "gemini-1.5-flash":      (0.075, 0.30),
        "gemini-1.5-flash-8b":   (0.0375, 0.15),
    },
    "mistral": {
        "mistral-large-latest":  (2.00,  6.00),
        "mistral-small-latest":  (0.20,  0.60),
        "codestral-latest":      (0.20,  0.60),
        "open-mistral-7b":       (0.25,  0.25),
        "open-mixtral-8x7b":     (0.70,  0.70),
    },
    "groq": {
        "llama-3.1-70b-versatile": (0.59,  0.79),
        "llama-3.1-8b-instant":    (0.05,  0.08),
        "llama3-70b-8192":         (0.59,  0.79),
        "llama3-8b-8192":          (0.05,  0.08),
        "mixtral-8x7b-32768":      (0.24,  0.24),
    },
    "together": {
        "meta-llama/Llama-3-70b-chat-hf":         (0.90,  0.90),
        "meta-llama/Llama-3-8b-chat-hf":          (0.20,  0.20),
        "mistralai/Mixtral-8x7B-Instruct-v0.1":   (0.60,  0.60),
        "Qwen/Qwen2-72B-Instruct":                (0.90,  0.90),
    },
    "ollama": {},          # local, $0
    "litellm_proxy": {},   # depends on what the proxy routes to; left to the proxy to report
    "portkey": {},         # depends on virtual key routing
    "openrouter": {},      # depends on routed upstream model — OpenRouter bills per-token at its own table
}


def get_price(provider: str, model: str) -> Optional[Tuple[float, float]]:
    """Return (input_price_per_1m, output_price_per_1m) USD, or None if unknown."""
    table = PRICING.get(provider or "")
    if not table:
        return None
    return table.get(model)


def estimate_cost_usd(
    provider: Optional[str],
    model: Optional[str],
    input_tokens: int,
    output_tokens: int,
) -> Optional[float]:
    """Compute USD cost for a single call. Returns None if pricing unknown.

    Local-only providers (ollama / litellm_proxy / portkey) intentionally return
    0.0 so the UI can show "$0.00" instead of "unknown"."""
    if provider in {"ollama"}:
        return 0.0
    if provider in {"litellm_proxy", "portkey", "openrouter"} and model not in (PRICING.get(provider) or {}):
        # We don't know what the gateway routes to; mark as unknown.
        return None
    price = get_price(provider or "", model or "")
    if not price:
        return None
    pin, pout = price
    return round(((input_tokens or 0) * pin + (output_tokens or 0) * pout) / 1_000_000, 6)


def extract_token_usage(response_dict: Dict[str, Any]) -> Tuple[int, int]:
    """Pull (input_tokens, output_tokens) from a LiteLLM response dict.

    LiteLLM normalises every provider's usage field to OpenAI's shape:
        { "usage": { "prompt_tokens": int, "completion_tokens": int, ... } }
    Returns (0, 0) when usage is missing — never raises."""
    usage = (response_dict or {}).get("usage") or {}
    if not isinstance(usage, dict):
        # Some upstream errors return usage as a string/None; we promise to never raise.
        return 0, 0
    inp = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
    out = usage.get("completion_tokens") or usage.get("output_tokens") or 0
    try:
        return int(inp), int(out)
    except (TypeError, ValueError):
        return 0, 0
