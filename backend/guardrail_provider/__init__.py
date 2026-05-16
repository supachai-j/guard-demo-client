"""Guardrail provider abstraction.

Each provider (Lakera, OpenAI Moderation, Bedrock Guardrails, …) exposes the
same `check_interaction()` signature and returns the same Lakera-shaped status
dict, so the agent loop and UI overlay don't need to care which provider is
configured.

See registry.py for the catalog of providers, base.py for the contract.
"""

from .base import GuardrailProvider, GuardrailStatus
from .registry import (
    GUARDRAIL_PROVIDERS,
    active_provider_id,
    list_providers_for_ui,
    resolve_provider,
)

__all__ = [
    "GuardrailProvider",
    "GuardrailStatus",
    "GUARDRAIL_PROVIDERS",
    "active_provider_id",
    "list_providers_for_ui",
    "resolve_provider",
]
