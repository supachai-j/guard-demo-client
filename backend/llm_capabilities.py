"""Per-model capability hints.

Provider gateways sometimes return opaque errors (e.g. ThaiLLM's OpenAI-
compatible layer surfacing `OpenAIException - request body must be valid
JSON`) when a text-only model receives OpenAI-style vision content blocks.
This module lets the chat route short-circuit such requests with a clear,
actionable message before the LLM call.

Conservative: only models we've **confirmed** text-only-but-shaped-like-OpenAI
go in `_KNOWN_TEXT_ONLY`. Anything not listed defaults to "we don't know —
try it and let the provider speak." That keeps OpenRouter / Ollama /
LiteLLM proxy / Kong-routed models out of the way, since capability for
those depends on the underlying upstream we can't introspect.
"""
from typing import Optional

# Substring matches — case-insensitive against the model id. Confirmed
# text-only via direct test. Add entries as new gateways with opaque
# vision-failure errors come up.
_KNOWN_TEXT_ONLY: tuple[str, ...] = (
    "thaillm",
    "openthaigpt",
)


def is_known_text_only(model_id: Optional[str]) -> bool:
    if not model_id:
        return False
    m = model_id.lower()
    return any(k in m for k in _KNOWN_TEXT_ONLY)


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
