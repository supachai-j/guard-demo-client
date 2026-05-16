"""Catalog of supported guardrail providers, plus a resolver that picks the
active one based on AppConfig.guardrail_provider.

Frontend Admin dropdown reads `list_providers_for_ui()`. Agent loop reads
`resolve_provider(cfg)` and calls `.check_interaction()` on whatever comes back.
"""

from typing import Any, Dict, List, Optional

from .azure_content_safety_provider import AzureContentSafetyProvider
from .base import GuardrailProvider
from .bedrock_provider import BedrockGuardrailsProvider
from .cloudflare_provider import CloudflareFirewallForAIProvider
from .lakera_provider import LakeraProvider
from .openai_moderation_provider import OpenAIModerationProvider
from .palo_alto_provider import PaloAltoAirsProvider

GUARDRAIL_PROVIDERS: Dict[str, GuardrailProvider] = {
    LakeraProvider.id: LakeraProvider(),
    OpenAIModerationProvider.id: OpenAIModerationProvider(),
    BedrockGuardrailsProvider.id: BedrockGuardrailsProvider(),
    AzureContentSafetyProvider.id: AzureContentSafetyProvider(),
    PaloAltoAirsProvider.id: PaloAltoAirsProvider(),
    CloudflareFirewallForAIProvider.id: CloudflareFirewallForAIProvider(),
}


def active_provider_id(cfg: Any) -> str:
    """Read AppConfig.guardrail_provider, default to 'lakera' for legacy rows."""
    pid = getattr(cfg, "guardrail_provider", None) if cfg else None
    if pid and pid in GUARDRAIL_PROVIDERS:
        return pid
    return "lakera"


def resolve_provider(cfg: Any) -> Optional[GuardrailProvider]:
    """Return the configured provider instance, or None if it isn't ready
    (missing key, missing config etc.).

    Callers should fall back to "guardrail disabled" behavior when this
    returns None — same as today's check for `lakera_enabled and lakera_api_key`.
    """
    pid = active_provider_id(cfg)
    provider = GUARDRAIL_PROVIDERS.get(pid)
    if not provider:
        return None
    if not provider.is_configured(cfg):
        return None
    return provider


# Per-provider UI metadata. Keys mirror the AppConfig column names so the
# Admin Console can render the right form fields.
_PROVIDER_UI_FIELDS: Dict[str, Dict[str, Any]] = {
    "lakera": {
        "fields": [
            {"name": "lakera_api_key", "label": "Lakera API Key", "type": "password", "placeholder": "lk-..."},
            {"name": "lakera_project_id", "label": "Lakera Project ID (optional)", "type": "text", "placeholder": "project-..."},
        ],
        "docs_url": "https://docs.lakera.ai/",
        "summary": "Direct REST POST /v2/guard. Best detector coverage for prompt-injection + PII.",
    },
    "openai_moderation": {
        "fields": [],  # reuses openai_api_key already configured for the LLM
        "docs_url": "https://platform.openai.com/docs/guides/moderation",
        "summary": "Reuses the OpenAI API key configured for the LLM. Free; no prompt-attack detector — moderated_content only.",
    },
    "bedrock": {
        "fields": [
            {"name": "bedrock_guardrail_id", "label": "Bedrock Guardrail ID", "type": "text", "placeholder": "xxxxxxxxxxxx"},
            {"name": "bedrock_guardrail_version", "label": "Guardrail Version", "type": "text", "placeholder": "DRAFT or numeric"},
            {"name": "bedrock_region", "label": "AWS Region", "type": "text", "placeholder": "us-east-1"},
            {"name": "bedrock_access_key_id", "label": "AWS Access Key ID (optional)", "type": "text", "placeholder": "AKIA..."},
            {"name": "bedrock_secret_access_key", "label": "AWS Secret Access Key (optional)", "type": "password", "placeholder": "leave blank to use default credential chain"},
        ],
        "docs_url": "https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html",
        "summary": "Standalone ApplyGuardrail API. Requires a guardrail pre-created in the Bedrock console.",
    },
    "azure_content_safety": {
        "fields": [
            {"name": "azure_content_safety_endpoint", "label": "Resource Endpoint", "type": "text", "placeholder": "https://<resource>.cognitiveservices.azure.com"},
            {"name": "azure_content_safety_key", "label": "Subscription Key", "type": "password", "placeholder": "your Ocp-Apim-Subscription-Key"},
        ],
        "docs_url": "https://learn.microsoft.com/en-us/azure/ai-services/content-safety/",
        "summary": "Calls text:analyze (Hate/SelfHarm/Sexual/Violence severity 0-6) + text:shieldPrompt (user-prompt + document injection) in parallel.",
    },
    "palo_alto_airs": {
        "fields": [
            {"name": "palo_alto_api_key", "label": "AIRS API Token (x-pan-token)", "type": "password", "placeholder": "your AIRS API token"},
            {"name": "palo_alto_profile_name", "label": "AI Security Profile name", "type": "text", "placeholder": "e.g. default-ai-profile"},
            {"name": "palo_alto_host", "label": "AIRS Host (region)", "type": "text", "placeholder": "service.api.aisecurity.paloaltonetworks.com"},
        ],
        "docs_url": "https://pan.dev/prisma-airs/api/airuntimesecurity/",
        "summary": "Calls POST /v1/scan/sync/request. Detects prompt injection, DLP, URL cats, toxic content, malicious code. Requires an AI security profile preconfigured in Strata Cloud Manager.",
    },
    "cloudflare_firewall_ai": {
        "fields": [
            {"name": "cloudflare_account_id", "label": "Cloudflare Account ID", "type": "text", "placeholder": "32-char hex string"},
            {"name": "cloudflare_api_token", "label": "Cloudflare API Token (Workers AI scope)", "type": "password", "placeholder": "your Cloudflare API token"},
            {"name": "cloudflare_gateway_id", "label": "AI Gateway ID (optional)", "type": "text", "placeholder": "route through AI Gateway when set"},
        ],
        "docs_url": "https://developers.cloudflare.com/ai-gateway/firewall-for-ai/",
        "summary": "Calls Workers AI @cf/meta/llama-guard-3-8b (MLCommons S1–S14 taxonomy). Routes through AI Gateway when a gateway ID is set.",
    },
}


def list_providers_for_ui() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for pid, provider in GUARDRAIL_PROVIDERS.items():
        meta = _PROVIDER_UI_FIELDS.get(pid, {})
        out.append({
            "id": pid,
            "display_name": provider.display_name,
            "fields": meta.get("fields", []),
            "docs_url": meta.get("docs_url"),
            "summary": meta.get("summary"),
        })
    return out
