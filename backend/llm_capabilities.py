"""Per-model capability hints.

Two related but separate jobs:

1. **Chat image-gate.** Provider gateways sometimes return opaque errors
   (e.g. ThaiLLM's OpenAI-compatible layer surfacing
   `OpenAIException - request body must be valid JSON`) when a text-only
   model receives OpenAI-style vision content blocks. `is_known_text_only`
   + `reject_image_request_message` let the chat route short-circuit
   such requests with a clear message before the LLM call.

2. **OCR pre-scan resolver.** §4.3.14 OCR-before-guardrail needs a
   vision-capable model. Historically it just used `cfg.openai_model`,
   which silently failed (and bypassed the guardrail) when the active
   LLM was text-only. `resolve_ocr_model(cfg)` picks the right model:
   explicit override → active LLM (if vision-capable) → smart fallback
   to any configured vision-capable provider → None.

Conservative deny/allow lists. Only models we've **confirmed** go in
either list. Anything unlisted defaults to "we don't know — let the
provider speak" so OpenRouter / Ollama / LiteLLM proxy / Kong-routed
models (where capability depends on an upstream we can't introspect)
aren't false-rejected.
"""
from dataclasses import dataclass
from typing import Any, Optional

# Substring matches — case-insensitive against the model id. Confirmed
# text-only via direct test. Add entries as new gateways with opaque
# vision-failure errors come up.
_KNOWN_TEXT_ONLY: tuple[str, ...] = (
    "thaillm",
    "openthaigpt",
)


# Substring matches for models we've confirmed support OpenAI-style vision
# content blocks (text + image_url in a content array). Used to validate
# the OCR model choice and to power UI dropdowns of "models that can do
# vision". Conservative — when in doubt, leave a model off and let the
# operator override explicitly if they know it works.
_KNOWN_VISION_CAPABLE: tuple[str, ...] = (
    # OpenAI
    "gpt-4o",
    "gpt-4-turbo",
    "gpt-4-vision",
    # Anthropic — every Claude 3+ model supports vision
    "claude-3",
    "claude-opus",
    "claude-sonnet",
    "claude-haiku",
    # Google Gemini — 1.5 and 2.x families
    "gemini-1.5",
    "gemini-2",
    "gemini-pro-vision",
    # Mistral — Pixtral family
    "pixtral",
)


# Ordered candidates for the smart OCR fallback: cheap + fast + reliable
# vision models, picked when no explicit override is set and the active
# LLM is text-only. Each entry maps to the AppConfig credential field
# we check and the provider id (used against disabled_providers).
@dataclass(frozen=True)
class _VisionCandidate:
    model: str
    provider_id: str          # matches values used in disabled_providers
    api_key_attr: str         # attribute on cfg holding the credential


_VISION_FALLBACK_CHAIN: tuple[_VisionCandidate, ...] = (
    _VisionCandidate("gpt-4o-mini", "openai", "openai_api_key"),
    _VisionCandidate("gemini-1.5-flash", "google", "google_api_key"),
    _VisionCandidate("claude-3-haiku-20240307", "anthropic", "anthropic_api_key"),
)


def is_known_text_only(model_id: Optional[str]) -> bool:
    if not model_id:
        return False
    m = model_id.lower()
    return any(k in m for k in _KNOWN_TEXT_ONLY)


def is_known_vision_capable(model_id: Optional[str]) -> bool:
    if not model_id:
        return False
    m = model_id.lower()
    return any(k in m for k in _KNOWN_VISION_CAPABLE)


def reject_image_request_message(model_id: str) -> str:
    """User-facing explanation when blocking an image request against a
    known text-only model. Names example vision-capable swaps so the
    operator can act without leaving the chat."""
    return (
        f"The active model '{model_id}' does not support image inputs. "
        f"Switch to a vision-capable model (e.g. OpenAI gpt-4o, "
        f"Anthropic claude-3 family, or Google gemini-1.5) in "
        f"Admin → LLM, or remove the image and resend."
    )


def smart_ocr_fallback(cfg: Any) -> Optional[str]:
    """First vision-capable model in _VISION_FALLBACK_CHAIN whose provider
    has a credential configured AND isn't operator-disabled. Used when
    OCR needs a model but the active LLM is text-only (or unknown) and
    no explicit cfg.ocr_model is set.

    Returns None if nothing qualifies — caller then falls through to the
    existing graceful-degrade-to-"" contract."""
    disabled = set(getattr(cfg, "disabled_providers", None) or [])
    for cand in _VISION_FALLBACK_CHAIN:
        if cand.provider_id in disabled:
            continue
        key = getattr(cfg, cand.api_key_attr, None)
        if key:
            return cand.model
    return None


def resolve_ocr_model(cfg: Any) -> tuple[Optional[str], str]:
    """Pick the model to use for OCR pre-scan.

    Returns `(model_id, source)` where source is one of:
      - "explicit"  — cfg.ocr_model was set
      - "active"    — fell through to the active LLM (cfg.openai_model)
                      because it's a known vision-capable model
      - "fallback"  — smart_ocr_fallback chose a configured alternative
                      (active LLM was text-only or unknown)
      - "none"      — nothing usable; caller should degrade gracefully

    Source is returned (and logged by the OCR module) so the operator can
    see in the backend log which path fired — important for debugging the
    §4.3.14 image-injection guardrail."""
    explicit = getattr(cfg, "ocr_model", None)
    if explicit:
        return explicit, "explicit"

    active = getattr(cfg, "openai_model", None)
    # Use the active LLM only when we've confirmed it can do vision. Just
    # "not in the deny-list" isn't enough — anything unconfirmed is sent
    # to the fallback, since the failure mode (silent guardrail bypass)
    # is worse than the cost of one extra cheap vision call.
    if is_known_vision_capable(active):
        return active, "active"

    fallback = smart_ocr_fallback(cfg)
    if fallback:
        return fallback, "fallback"

    return None, "none"
