"""Tests for backend.providers — multi-provider registry + dispatch helpers."""

from types import SimpleNamespace

from backend.providers import (
    PROVIDERS,
    credentials_configured,
    list_providers_for_ui,
    provider_api_key,
    provider_base_url,
    provider_id,
    provider_meta,
    provider_static_models,
    to_litellm_model,
)


def _cfg(**fields):
    """Build a lightweight stand-in for AppConfig without touching the ORM."""
    defaults = dict.fromkeys(("llm_provider", "use_litellm", "openai_api_key", "anthropic_api_key", "google_api_key", "mistral_api_key", "groq_api_key", "together_api_key", "openrouter_api_key", "litellm_virtual_key", "portkey_api_key", "portkey_base_url", "ollama_base_url", "litellm_base_url"))
    defaults.update(fields)
    return SimpleNamespace(**defaults)


# ---------- provider_id resolution ---------------------------------------

def test_provider_id_defaults_to_openai_when_no_cfg():
    assert provider_id(None) == "openai"


def test_provider_id_returns_saved_value():
    assert provider_id(_cfg(llm_provider="anthropic")) == "anthropic"
    assert provider_id(_cfg(llm_provider="openrouter")) == "openrouter"


def test_provider_id_legacy_use_litellm_migration():
    """Old rows with use_litellm=1 but no llm_provider must resolve to litellm_proxy."""
    assert provider_id(_cfg(use_litellm=True)) == "litellm_proxy"


def test_provider_id_falls_back_to_openai_on_unknown():
    assert provider_id(_cfg(llm_provider="invented")) == "openai"


# ---------- provider_meta ------------------------------------------------

def test_provider_meta_returns_dict_for_active():
    meta = provider_meta(_cfg(llm_provider="anthropic"))
    assert meta["display_name"].startswith("Anthropic")
    assert meta["litellm_prefix"] == "anthropic/"


# ---------- key + base_url lookups ---------------------------------------

def test_provider_api_key_reads_correct_field():
    cfg = _cfg(llm_provider="anthropic", anthropic_api_key="sk-ant-xyz")
    assert provider_api_key(cfg) == "sk-ant-xyz"


def test_provider_api_key_returns_none_when_unset():
    assert provider_api_key(_cfg(llm_provider="anthropic")) is None


def test_provider_api_key_returns_none_for_keyless_provider():
    # Ollama has no key_field
    assert provider_api_key(_cfg(llm_provider="ollama")) is None


def test_provider_base_url_returns_default_when_unset():
    """Ollama provider has a default_base_url and no override."""
    cfg = _cfg(llm_provider="ollama")
    assert provider_base_url(cfg) == "http://localhost:11434"


def test_provider_base_url_returns_override_when_set():
    cfg = _cfg(llm_provider="ollama", ollama_base_url="http://my-ollama:11434")
    assert provider_base_url(cfg) == "http://my-ollama:11434"


def test_provider_base_url_none_for_providers_without_one():
    """OpenAI / Anthropic don't expose a base_url field."""
    assert provider_base_url(_cfg(llm_provider="openai")) is None


# ---------- to_litellm_model translation ---------------------------------

def test_to_litellm_model_unchanged_for_openai():
    cfg = _cfg(llm_provider="openai")
    assert to_litellm_model(cfg, "gpt-4o") == "gpt-4o"


def test_to_litellm_model_prefixes_anthropic():
    cfg = _cfg(llm_provider="anthropic")
    assert to_litellm_model(cfg, "claude-opus-4-7") == "anthropic/claude-opus-4-7"


def test_to_litellm_model_does_not_double_prefix():
    """Idempotent: if the model already starts with the prefix, leave it alone."""
    cfg = _cfg(llm_provider="anthropic")
    assert to_litellm_model(cfg, "anthropic/claude-opus-4-7") == "anthropic/claude-opus-4-7"


def test_to_litellm_model_openrouter_layers_correctly():
    """OpenRouter model ids already contain a vendor/family segment."""
    cfg = _cfg(llm_provider="openrouter")
    assert to_litellm_model(cfg, "anthropic/claude-3.5-sonnet") == "openrouter/anthropic/claude-3.5-sonnet"


def test_to_litellm_model_empty_string_passthrough():
    cfg = _cfg(llm_provider="anthropic")
    assert to_litellm_model(cfg, "") == ""


# ---------- credentials_configured ---------------------------------------

def test_credentials_configured_false_without_key():
    assert credentials_configured(_cfg(llm_provider="anthropic")) is False


def test_credentials_configured_true_with_key():
    cfg = _cfg(llm_provider="anthropic", anthropic_api_key="sk-ant-xyz")
    assert credentials_configured(cfg) is True


def test_credentials_configured_true_for_keyless_provider():
    """Ollama has no key requirement."""
    assert credentials_configured(_cfg(llm_provider="ollama")) is True


def test_credentials_configured_false_when_no_cfg():
    assert credentials_configured(None) is False


# ---------- UI catalog (drives the Admin dropdowns) ----------------------

def test_list_providers_for_ui_includes_openrouter():
    ids = {p["id"] for p in list_providers_for_ui()}
    assert {"openai", "anthropic", "openrouter", "portkey"}.issubset(ids)


def test_list_providers_for_ui_twelve_total():
    """We currently ship 12 LLM providers — guard against accidental removals."""
    assert len(list_providers_for_ui()) == 12


def test_list_providers_for_ui_payload_shape():
    for entry in list_providers_for_ui():
        assert "id" in entry
        assert "display_name" in entry
        assert "needs_key" in entry
        assert isinstance(entry["models"], list)


def test_provider_static_models_returns_list_for_known():
    models = provider_static_models("anthropic")
    assert isinstance(models, list) and len(models) >= 1
    # Should be Claude 4.x family after the 2026 model refresh
    assert any(m.startswith("claude-") for m in models)


def test_provider_static_models_empty_for_unknown():
    assert provider_static_models("not-a-real-provider") == []


# ---------- spot-check Anthropic deprecated-IDs scrubbed -----------------

def test_anthropic_models_dont_include_deprecated_snapshots():
    """The 2024-10-22 Claude snapshot returns 404 on Anthropic in 2026."""
    models = PROVIDERS["anthropic"]["models"]
    assert "claude-3-5-sonnet-20241022" not in models
    assert "claude-3-opus-20240229" not in models


def test_openrouter_registered():
    assert "openrouter" in PROVIDERS
    assert PROVIDERS["openrouter"]["litellm_prefix"] == "openrouter/"
    assert PROVIDERS["openrouter"]["key_field"] == "openrouter_api_key"
