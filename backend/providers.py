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
        # Claude 4.x family — older 3.x snapshots are deprecated on the API as of
        # early 2026 and return 404. Keep this list aligned with
        # https://docs.anthropic.com/en/docs/about-claude/models.
        "models": [
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
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
    "openrouter": {
        "display_name": "OpenRouter (AI Gateway)",
        "key_field": "openrouter_api_key",
        "base_url_field": None,
        # LiteLLM routes via the `openrouter/` prefix; OpenRouter model ids
        # already contain a vendor/family segment (e.g. anthropic/claude-3.5-sonnet),
        # so the final dispatched model string becomes openrouter/anthropic/claude-3.5-sonnet.
        "litellm_prefix": "openrouter/",
        "needs_key": True,
        "models": [
            "anthropic/claude-3.5-sonnet",
            "anthropic/claude-3.5-haiku",
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
            "google/gemini-2.0-flash-exp",
            "google/gemini-pro-1.5",
            "meta-llama/llama-3.1-405b-instruct",
            "meta-llama/llama-3.1-70b-instruct",
            "mistralai/mistral-large",
            "deepseek/deepseek-chat",
            "x-ai/grok-2",
            "qwen/qwen-2.5-72b-instruct",
        ],
    },
    "thaillm": {
        "display_name": "ThaiLLM (national Thai LLM gateway)",
        "key_field": "thaillm_api_key",
        "base_url_field": "thaillm_base_url",
        "default_base_url": "http://thaillm.or.th/api",
        # OpenAI-compatible (POST /v1/chat/completions + Bearer key); routed
        # via LiteLLM's openai custom_llm_provider — see _build_litellm_kwargs.
        "litellm_prefix": "",
        # Kong key-auth plugin in front of the cluster — chat completions
        # return 401 "No API key found" if `apikey:` header is missing. The
        # llm_client dispatch path injects that header for us; setting
        # needs_key=True enforces key presence so we fail fast in the UI
        # instead of silently dispatching a request that the gateway will block.
        "needs_key": True,
        # Static fallback list — verified against /v1/models on 2026-05-17.
        # llm_client.get_models() also dynamically fetches /v1/models when
        # available so this list will be refreshed at call time.
        "models": [
            "OpenThaiGPT-ThaiLLM-8B-Instruct-v7.2",
            "Typhoon-S-ThaiLLM-8B-Instruct",
            "Pathumma-ThaiLLM-qwen3-8b-think-3.0.0",
            "THaLLE-0.2-ThaiLLM-8B-fa",
        ],
    },
    "portkey": {
        "display_name": "Portkey (AI Gateway)",
        "key_field": "portkey_api_key",
        # Optional self-managed deployment URL (otherwise hits api.portkey.ai).
        "base_url_field": "portkey_base_url",
        "default_base_url": "https://api.portkey.ai/v1",
        # Portkey is OpenAI-compatible; model name is whatever the virtual key resolves to.
        "litellm_prefix": "",
        "needs_key": True,
        "models": [
            "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4",
            "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229",
            "gemini-1.5-pro", "gemini-1.5-flash",
            "mixtral-8x7b-32768", "llama-3.1-70b-versatile", "llama-3.1-8b-instant",
        ],
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
