"""Credential masking for the public /api/config read.

Lives in its own tiny module so security tests can import the mask list
without loading the rest of the FastAPI app (which pulls in chromadb,
numpy, grpc — slow at best, occasionally CPU-instruction-incompatible
on CI runners).
"""

from copy import copy as _copy
from typing import Any

# Fields that must be hidden from non-admin callers (every credential).
SECRET_CONFIG_FIELDS = (
    "openai_api_key",
    "anthropic_api_key",
    "google_api_key",
    "mistral_api_key",
    "groq_api_key",
    "together_api_key",
    "openrouter_api_key",
    "lakera_api_key",
    "litellm_virtual_key",
    "bedrock_access_key_id",
    "bedrock_secret_access_key",
    "azure_content_safety_key",
    "palo_alto_api_key",
    "portkey_api_key",
    "portkey_virtual_key",
    "thaillm_api_key",
    "cloudflare_api_token",
)


def redact_config(config: Any, *, authenticated: bool) -> Any:
    """Return a config view with secrets blanked for non-admins.

    The Landing page reads /api/config for branding fields; we don't want
    those visitors to see API keys. The AdminConsole sends a Bearer token
    so it gets the unredacted config.
    """
    if authenticated:
        return config
    safe = _copy(config)
    for field in SECRET_CONFIG_FIELDS:
        if hasattr(safe, field) and getattr(safe, field, None):
            setattr(safe, field, "***")
    return safe
