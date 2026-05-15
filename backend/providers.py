"""Multi-provider LLM registry.

Defines the providers exposed in Admin → Security, the models each provider
offers, and how to translate the (provider, model) pair into the model string
LiteLLM expects (e.g. ``anthropic/claude-3-5-sonnet-20241022``).
"""

from typing import Any, Dict, List, Optional

from .models import AppConfig


# Provider id -> metadata. The id is what we store in AppConfig.llm_provider.
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "display_name": "OpenAI",
        "key_field": "openai_api_key",
        "base_url_field": None,
        "litellm_prefix": "",  # OpenAI models pass through unprefixed
        "needs_key": True,
        "models": [
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo",
        ],
    },
    "anthropic": {
        "display_name": "Anthropic (Claude)",
        "key_field": "anthropic_api_key",
        "base_url_field": None,
        "litellm_prefix": "anthropic/",
        "needs_key": True,
        "models": [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
        ],
    },
    "google": {
        "display_name": "Google (Gemini)",
        "key_field": "google_api_key",
        "base_url_field": None,
        "litellm_prefix": "gemini/",
        "needs_key": True,
        "models": [
            "gemini-2.0-flash-exp",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "gemini-1.5-flash-8b",
        ],
    },
    "mistral": {
        "display_name": "Mistral",
        "key_field": "mistral_api_key",
        "base_url_field": None,
        "litellm_prefix": "mistral/",
        "needs_key": True,
        "models": [
            "mistral-large-latest",
            "mistral-small-latest",
            "codestral-latest",
            "open-mistral-7b",
            "open-mixtral-8x7b",
        ],
    },
    "groq": {
        "display_name": "Groq (open-weights, fast)",
        "key_field": "groq_api_key",
        "base_url_field": None,
        "litellm_prefix": "groq/",
        "needs_key": True,
        "models": [
            "llama-3.1-70b-versatile",
            "llama-3.1-8b-instant",
            "llama3-70b-8192",
            "llama3-8b-8192",
            "mixtral-8x7b-32768",
        ],
    },
    "together": {
        "display_name": "Together AI",
        "key_field": "together_api_key",
        "base_url_field": None,
        "litellm_prefix": "together_ai/",
        "needs_key": True,
        "models": [
            "meta-llama/Llama-3-70b-chat-hf",
            "meta-llama/Llama-3-8b-chat-hf",
            "mistralai/Mixtral-8x7B-Instruct-v0.1",
            "Qwen/Qwen2-72B-Instruct",
        ],
    },
    "ollama": {
        "display_name": "Ollama (local)",
        "key_field": None,  # no API key, just a base URL
        "base_url_field": "ollama_base_url",
        "default_base_url": "http://localhost:11434",
        "litellm_prefix": "ollama/",
        "needs_key": False,
        "models": [
            "llama3",
            "llama3.1",
            "llama3.2",
            "mistral",
            "codellama",
            "qwen2",
            "phi3",
        ],
    },
    "litellm_proxy": {
        "display_name": "LiteLLM proxy (self-hosted)",
        "key_field": "litellm_virtual_key",
        "base_url_field": "litellm_base_url",
        "default_base_url": "http://localhost:4000",
        # Model id is whatever the proxy advertises; no LiteLLM-side prefix
        "litellm_prefix": "",
        "needs_key": False,  # some proxies allow empty bearer
        "models": [],  # fetched dynamically from /v1/models
    },
}


def provider_id(cfg: Optional[AppConfig]) -> str:
    """Resolve the active provider id, defaulting sensibly for legacy rows."""
    if not cfg:
        return "openai"
    pid = getattr(cfg, "llm_provider", None)
    if pid and pid in PROVIDERS:
        return pid
    if getattr(cfg, "use_litellm", False):
        return "litellm_proxy"
    return "openai"


def provider_meta(cfg: Optional[AppConfig]) -> Dict[str, Any]:
    return PROVIDERS[provider_id(cfg)]


def provider_api_key(cfg: Optional[AppConfig]) -> Optional[str]:
    """Return the API key currently configured for the active provider, or None."""
    if not cfg:
        return None
    meta = provider_meta(cfg)
    field = meta.get("key_field")
    if not field:
        return None
    val = getattr(cfg, field, None)
    return val or None


def provider_base_url(cfg: Optional[AppConfig]) -> Optional[str]:
    """Return the base URL for providers that need one (LiteLLM proxy, Ollama)."""
    if not cfg:
        return None
    meta = provider_meta(cfg)
    field = meta.get("base_url_field")
    if not field:
        return None
    val = getattr(cfg, field, None) or meta.get("default_base_url")
    return val or None


def to_litellm_model(cfg: Optional[AppConfig], model_name: str) -> str:
    """Translate a stored model id into the model string LiteLLM expects."""
    meta = provider_meta(cfg)
    prefix = meta.get("litellm_prefix") or ""
    if not model_name:
        return model_name
    if prefix and model_name.startswith(prefix):
        return model_name
    return f"{prefix}{model_name}" if prefix else model_name


def provider_static_models(provider: str) -> List[str]:
    return list(PROVIDERS.get(provider, {}).get("models") or [])


def list_providers_for_ui() -> List[Dict[str, Any]]:
    """Shape used by GET /api/providers — what the UI dropdown renders."""
    return [
        {
            "id": pid,
            "display_name": meta["display_name"],
            "key_field": meta.get("key_field"),
            "base_url_field": meta.get("base_url_field"),
            "default_base_url": meta.get("default_base_url"),
            "needs_key": meta.get("needs_key", True),
            "models": list(meta.get("models") or []),
        }
        for pid, meta in PROVIDERS.items()
    ]


def credentials_configured(cfg: Optional[AppConfig]) -> bool:
    """Whether the active provider has enough config to make a call."""
    if not cfg:
        return False
    meta = provider_meta(cfg)
    if meta.get("needs_key"):
        return bool(provider_api_key(cfg))
    return True
