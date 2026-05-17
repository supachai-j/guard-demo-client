"""
Multi-provider LLM client. All chat + embedding traffic is routed through
litellm.completion / litellm.embedding so that providers (OpenAI, Anthropic,
Google, Mistral, Groq, Together, Ollama, self-hosted LiteLLM proxy) share one
dispatch path, including tool-calling translation.
"""
import ast
import copy
from typing import Any, Dict, List, Optional, Union

import httpx
import litellm
from litellm import completion as litellm_completion
from litellm import embedding as litellm_embedding
from litellm.exceptions import APIConnectionError, BadRequestError

from .database import get_db
from .models import AppConfig
from .providers import (
    PROVIDERS,
    provider_api_key,
    provider_base_url,
    provider_id,
    provider_static_models,
    to_litellm_model,
)

# Timeout for LiteLLM proxy /v1/models request (seconds)
LITELLM_MODELS_TIMEOUT = 10.0

# Kept for backward-compat with existing imports (some callers expect this).
STATIC_MODELS = provider_static_models("openai")


def _supports_custom_temperature(model: str) -> bool:
    """GPT-5 family rejects non-default temperature on chat completions."""
    name = (model or "").strip().lower()
    return not name.startswith("gpt-5")


class LiteLLMGuardrailError(Exception):
    """Raised when LiteLLM-proxy guardrails block a response and return detector details."""

    def __init__(self, message: str, lakera_status: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.lakera_status = lakera_status or {}


def _normalize_litellm_lakera_message_ids(status: Dict[str, Any]) -> Dict[str, Any]:
    """LiteLLM Lakera payloads can be offset by +1 vs direct Lakera indexing."""
    out = copy.deepcopy(status)

    def shift_entry(entry: Any) -> None:
        if not isinstance(entry, dict):
            return
        mid = entry.get("message_id")
        if isinstance(mid, int) and mid >= 1:
            entry["message_id"] = mid - 1

    for item in out.get("breakdown") or []:
        shift_entry(item)
    for item in out.get("payload") or []:
        shift_entry(item)
    return out


def _extract_litellm_guardrail_status(err: Exception) -> Optional[Dict[str, Any]]:
    """Best-effort extraction of Lakera guardrail details from a litellm error."""
    response = getattr(err, "response", None)
    payload: Dict[str, Any] = {}
    if response is not None:
        try:
            payload = response.json() if callable(getattr(response, "json", None)) else {}
        except Exception:
            payload = {}
    if not payload:
        message_raw = getattr(err, "message", None) or str(err)
        if isinstance(message_raw, str) and message_raw.strip():
            try:
                parsed = ast.literal_eval(message_raw.strip())
                if isinstance(parsed, dict):
                    payload = parsed
            except Exception:
                pass
    if not isinstance(payload, dict):
        return None
    error_obj = payload.get("error") if isinstance(payload, dict) else None
    nested = None
    if isinstance(error_obj, dict):
        direct = error_obj.get("lakera_guard_response")
        if isinstance(direct, dict):
            return _normalize_litellm_lakera_message_ids(direct)
        raw_message = error_obj.get("message")
        if isinstance(raw_message, str) and raw_message.strip():
            try:
                parsed_obj = ast.literal_eval(raw_message.strip())
            except Exception:
                parsed_obj = None
            if isinstance(parsed_obj, dict):
                nested = parsed_obj.get("lakera_guardrail_response")
                if isinstance(nested, dict):
                    return _normalize_litellm_lakera_message_ids(nested)
    if isinstance(payload.get("lakera_guard_response"), dict):
        return _normalize_litellm_lakera_message_ids(payload["lakera_guard_response"])
    return None


def effective_llm_api_key(cfg: Optional[AppConfig]) -> Optional[str]:
    """Bearer / API key for the active provider (None for ones that don't need one)."""
    return provider_api_key(cfg)


def llm_credentials_configured(cfg: Optional[AppConfig]) -> bool:
    """Whether the active provider has enough config to make a call."""
    if not cfg:
        return False
    pid = provider_id(cfg)
    meta = PROVIDERS.get(pid, {})
    if meta.get("needs_key"):
        return bool(provider_api_key(cfg))
    # ollama / litellm_proxy can run without a key
    return True


def _get_config() -> Optional[AppConfig]:
    db = next(get_db())
    try:
        return db.query(AppConfig).first()
    finally:
        db.close()


def _build_litellm_kwargs(
    cfg: Optional[AppConfig],
    model: str,
    temperature: Optional[float],
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None,
    litellm_guardrail_name: Optional[str] = None,
    litellm_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the kwargs passed to litellm.completion for the active provider."""
    pid = provider_id(cfg)
    model_str = to_litellm_model(cfg, model)
    kwargs: Dict[str, Any] = {
        "model": model_str,
        "messages": messages,
    }
    if temperature is not None and _supports_custom_temperature(model):
        kwargs["temperature"] = temperature
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    api_key = provider_api_key(cfg)
    if api_key:
        kwargs["api_key"] = api_key

    base_url = provider_base_url(cfg)
    if base_url:
        kwargs["api_base"] = base_url

    if pid == "litellm_proxy":
        # The self-hosted LiteLLM proxy expects OpenAI-style /v1; rewrite api_base accordingly.
        if base_url and not base_url.rstrip("/").endswith("/v1"):
            kwargs["api_base"] = f"{base_url.rstrip('/')}/v1"
        extra_body: Dict[str, Any] = {}
        if litellm_guardrail_name:
            extra_body["guardrails"] = [litellm_guardrail_name]
        if litellm_metadata:
            extra_body["metadata"] = litellm_metadata
        if extra_body:
            kwargs["extra_body"] = extra_body
        # Force OpenAI-compatible custom provider so LiteLLM proxies through correctly.
        kwargs["custom_llm_provider"] = "openai"
    elif pid == "thaillm":
        # ThaiLLM is an OpenAI-compatible custom endpoint. LiteLLM's openai
        # provider can hit any base URL — auto-append /v1 if the operator
        # entered the bare host URL (same convenience as litellm_proxy).
        if base_url and not base_url.rstrip("/").endswith("/v1"):
            kwargs["api_base"] = f"{base_url.rstrip('/')}/v1"
        kwargs["custom_llm_provider"] = "openai"
    elif pid == "portkey":
        # Portkey is OpenAI-compatible; auth via x-portkey-api-key + optional virtual key.
        # Self-managed deployments can override the gateway URL via portkey_base_url.
        custom_base = (getattr(cfg, "portkey_base_url", None) or "").strip()
        if custom_base:
            base = custom_base.rstrip("/")
            if not base.endswith("/v1"):
                base = f"{base}/v1"
            kwargs["api_base"] = base
        else:
            kwargs["api_base"] = "https://api.portkey.ai/v1"
        extra_headers: Dict[str, Any] = {
            "x-portkey-api-key": api_key or "",
        }
        virtual_key = getattr(cfg, "portkey_virtual_key", None)
        if virtual_key:
            extra_headers["x-portkey-virtual-key"] = virtual_key
        kwargs["extra_headers"] = extra_headers
        kwargs["custom_llm_provider"] = "openai"
    return kwargs


def chat_completion(
    messages: List[Dict[str, str]],
    model: str = "gpt-4o",
    temperature: Union[float, str, int, None] = 0.7,
    tools: Optional[List[Dict[str, Any]]] = None,
    config: Optional[AppConfig] = None,
    litellm_guardrail_name: Optional[str] = None,
    litellm_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Send chat completion through litellm. Returns OpenAI-style dict."""
    cfg = config or _get_config()
    if not llm_credentials_configured(cfg):
        raise Exception("Configure LLM API key in Admin → Security")

    try:
        temp_float: Optional[float] = float(temperature) if temperature is not None else 0.7
    except (ValueError, TypeError):
        temp_float = 0.7
    # UI uses 0-10 scale; LiteLLM expects 0-1 (or 0-2 depending on provider).
    if temp_float is not None and temp_float > 1.0:
        temp_float = temp_float / 10.0

    kwargs = _build_litellm_kwargs(
        cfg=cfg,
        model=model,
        temperature=temp_float,
        messages=messages,
        tools=tools,
        litellm_guardrail_name=litellm_guardrail_name,
        litellm_metadata=litellm_metadata,
    )

    pid = provider_id(cfg)
    try:
        response = litellm_completion(**kwargs)
    except APIConnectionError as e:
        if pid == "litellm_proxy":
            base = provider_base_url(cfg)
            raise Exception(f"LiteLLM proxy unreachable: {e}. Is the proxy running on {base}?") from e
        if pid == "ollama":
            base = provider_base_url(cfg)
            raise Exception(f"Ollama unreachable: {e}. Is Ollama running on {base}?") from e
        raise
    except BadRequestError as e:
        if pid == "litellm_proxy":
            lakera_status = _extract_litellm_guardrail_status(e)
            if lakera_status:
                raise LiteLLMGuardrailError(
                    "LiteLLM guardrail blocked this response.", lakera_status
                ) from e
        raise Exception(f"LLM API error: {e}") from e

    # litellm.completion returns a ModelResponse; .model_dump() yields the OpenAI-style dict
    # the rest of the codebase expects.
    if hasattr(response, "model_dump"):
        return response.model_dump()
    return dict(response)  # already a dict (unlikely)


def chat_completion_stream(
    messages: List[Dict[str, str]],
    model: str = "gpt-4o",
    temperature: Union[float, str, int, None] = 0.7,
    config: Optional[AppConfig] = None,
):
    """Streaming version of chat_completion. Yields content-delta strings.

    Tool-calls aren't supported in the streamed path — callers should use the
    non-streaming `chat_completion` when the agent needs tools."""
    cfg = config or _get_config()
    if not llm_credentials_configured(cfg):
        raise Exception("Configure LLM API key in Admin → Security")

    try:
        temp_float: Optional[float] = float(temperature) if temperature is not None else 0.7
    except (ValueError, TypeError):
        temp_float = 0.7
    if temp_float is not None and temp_float > 1.0:
        temp_float = temp_float / 10.0

    kwargs = _build_litellm_kwargs(
        cfg=cfg,
        model=model,
        temperature=temp_float,
        messages=messages,
        tools=None,
    )
    kwargs["stream"] = True

    pid = provider_id(cfg)
    try:
        response = litellm_completion(**kwargs)
    except APIConnectionError as e:
        if pid == "litellm_proxy":
            base = provider_base_url(cfg)
            raise Exception(f"LiteLLM proxy unreachable: {e}. Is the proxy running on {base}?") from e
        if pid == "ollama":
            base = provider_base_url(cfg)
            raise Exception(f"Ollama unreachable: {e}. Is Ollama running on {base}?") from e
        raise
    except BadRequestError as e:
        if pid == "litellm_proxy":
            lakera_status = _extract_litellm_guardrail_status(e)
            if lakera_status:
                raise LiteLLMGuardrailError(
                    "LiteLLM guardrail blocked this response.", lakera_status
                ) from e
        raise Exception(f"LLM API error: {e}") from e

    for chunk in response:
        try:
            if hasattr(chunk, "model_dump"):
                chunk_d = chunk.model_dump()
            else:
                chunk_d = dict(chunk)
            choices = chunk_d.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if content:
                yield content
        except Exception:
            continue


def get_embeddings(texts: List[str], config: Optional[AppConfig] = None) -> List[List[float]]:
    """Get embeddings for chunks. Only OpenAI and LiteLLM-proxy paths support embeddings today;
    other providers fall back to OpenAI's embedding endpoint if a key is configured, otherwise raise."""
    cfg = config or _get_config()
    if not cfg:
        raise Exception("Configure LLM API key in Admin → Security")

    pid = provider_id(cfg)
    # Embeddings: use the active provider when it sensibly supports them (openai/litellm_proxy),
    # else fall back to OpenAI direct using whatever openai_api_key the user has saved.
    if pid in {"openai", "litellm_proxy"} and llm_credentials_configured(cfg):
        api_key = provider_api_key(cfg) or ""
        api_base = provider_base_url(cfg)
        kwargs: Dict[str, Any] = {
            "model": "text-embedding-ada-002",
            "input": texts,
            "api_key": api_key,
        }
        if pid == "litellm_proxy" and api_base:
            kwargs["api_base"] = (
                api_base if api_base.rstrip("/").endswith("/v1") else f"{api_base.rstrip('/')}/v1"
            )
            kwargs["custom_llm_provider"] = "openai"
    else:
        fallback_key = cfg.openai_api_key
        if not fallback_key:
            raise Exception(
                "Embeddings require an OpenAI API key. Configure it in Admin → Security."
            )
        kwargs = {
            "model": "text-embedding-ada-002",
            "input": texts,
            "api_key": fallback_key,
        }

    try:
        response = litellm_embedding(**kwargs)
    except APIConnectionError as e:
        raise Exception(f"Embedding API unreachable: {e}") from e
    except Exception as e:
        raise Exception(f"Embedding API error: {e}") from e

    data = response.get("data") if isinstance(response, dict) else response.data
    out: List[List[float]] = []
    for entry in data or []:
        if isinstance(entry, dict):
            emb = entry.get("embedding")
        else:
            emb = getattr(entry, "embedding", None)
        if emb is not None:
            out.append(list(emb))
    return out


def _get_models_litellm_proxy(api_key: Optional[str], base_url: str) -> Optional[List[str]]:
    """Fetch key-specific models from a self-hosted LiteLLM proxy."""
    url = f"{base_url.rstrip('/')}/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        with httpx.Client(timeout=LITELLM_MODELS_TIMEOUT) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError, ValueError):
        return None
    data_list = data.get("data")
    if not isinstance(data_list, list):
        return None
    result = []
    for m in data_list:
        if isinstance(m, dict) and m.get("id"):
            result.append(str(m["id"]))
    return result if result else None


def _get_models_ollama(base_url: str) -> Optional[List[str]]:
    """Fetch installed models from a local Ollama server."""
    try:
        with httpx.Client(timeout=LITELLM_MODELS_TIMEOUT) as client:
            resp = client.get(f"{base_url.rstrip('/')}/api/tags")
            resp.raise_for_status()
            data = resp.json()
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError, ValueError):
        return None
    models = data.get("models")
    if not isinstance(models, list):
        return None
    names = []
    for m in models:
        if isinstance(m, dict) and m.get("name"):
            names.append(str(m["name"]))
    return names or None


def get_models(config: Optional[AppConfig] = None) -> List[str]:
    """List models for the active provider — dynamic when available, else static."""
    cfg = config or _get_config()
    pid = provider_id(cfg)
    if pid == "litellm_proxy":
        base = provider_base_url(cfg) or "http://localhost:4000"
        api_key = provider_api_key(cfg)
        dyn = _get_models_litellm_proxy(api_key, base)
        if dyn:
            return dyn
    if pid == "ollama":
        base = provider_base_url(cfg) or "http://localhost:11434"
        dyn = _get_models_ollama(base)
        if dyn:
            return dyn
    if pid == "thaillm":
        # OpenAI-compatible /v1/models — reuse the litellm_proxy helper since
        # it speaks the same {data: [{id: ...}, ...]} schema. Helper appends
        # /v1 itself, so strip a trailing /v1 first to avoid /v1/v1/models.
        base = (provider_base_url(cfg) or "http://thaillm.or.th/api").rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        dyn = _get_models_litellm_proxy(provider_api_key(cfg), base)
        if dyn:
            return dyn
    return provider_static_models(pid) or STATIC_MODELS


def ensure_active_model_valid(config: AppConfig, db) -> None:
    """If the saved `openai_model` isn't in the active provider's model list,
    swap it for the first valid option and persist. Called at the top of
    every chat/replay handler so a provider switch doesn't leave the row
    pointing at a model the new provider doesn't have."""
    valid_models = get_models(config)
    if valid_models and config.openai_model not in valid_models:
        config.openai_model = valid_models[0]
        db.commit()
        db.refresh(config)


# Silence noisy litellm logging by default (callers can override if they want)
litellm.suppress_debug_info = True
