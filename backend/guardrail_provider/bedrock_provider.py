"""AWS Bedrock Guardrails adapter — calls the standalone ApplyGuardrail API.

Requires boto3 + an AWS-keyed AppConfig (region, access key, secret, plus the
guardrail id/version pre-created in Bedrock). Maps the Bedrock response shape
into our Lakera-style status so the existing UI works unchanged.

ApplyGuardrail docs:
https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ApplyGuardrail.html
"""

import logging
from typing import Any, Dict, List, Optional

from .. import lakera as legacy_lakera
from .base import GuardrailProvider, GuardrailStatus, classify_http, make_error_status

logger = logging.getLogger(__name__)


# Bedrock content-policy types and our normalised detector_type.
_CONTENT_POLICY_MAP = {
    "HATE": "moderated_content/hate",
    "INSULTS": "moderated_content/profanity",
    "SEXUAL": "moderated_content/sexual",
    "VIOLENCE": "moderated_content/violence",
    "MISCONDUCT": "moderated_content/crime",
    "PROMPT_ATTACK": "prompt_attack",
}

# Bedrock sensitive-information categories → PII detector_type.
_PII_MAP = {
    "ADDRESS": "pii/address",
    "AGE": "pii/age",
    "CREDIT_DEBIT_CARD_NUMBER": "pii/credit_card",
    "EMAIL": "pii/email",
    "INTERNATIONAL_BANK_ACCOUNT_NUMBER": "pii/iban_code",
    "IP_ADDRESS": "pii/ip_address",
    "PHONE": "pii/phone",
    "SSN": "pii/us_social_security_number",
    "US_SOCIAL_SECURITY_NUMBER": "pii/us_social_security_number",
    "DRIVER_ID": "pii/driver_id",
    "PASSPORT_NUMBER": "pii/passport_number",
}


def _classify_botocore_exception(e: Exception) -> tuple:
    """Map a botocore exception to (error_class, http_status_or_None).

    AccessDenied / UnrecognizedClient / InvalidSignatureException → auth_failed
    ThrottlingException / TooManyRequestsException                → rate_limited
    ServiceUnavailableException / InternalServerException         → upstream_outage
    EndpointConnectionError / ConnectTimeoutError / ReadTimeout   → transport_error
    """
    try:
        from botocore.exceptions import ClientError, EndpointConnectionError  # type: ignore
        from botocore.exceptions import ConnectionError as BotoConnError
    except Exception:
        return "transport_error", None

    if isinstance(e, EndpointConnectionError) or isinstance(e, BotoConnError):
        return "transport_error", None
    if isinstance(e, ClientError):
        resp = getattr(e, "response", None) or {}
        code = ((resp.get("Error") or {}).get("Code")) or ""
        http_status = ((resp.get("ResponseMetadata") or {}).get("HTTPStatusCode"))
        auth_codes = {
            "AccessDeniedException", "UnrecognizedClientException", "InvalidSignatureException",
            "MissingAuthenticationTokenException", "ExpiredTokenException",
            "ResourceNotFoundException",  # bedrock returns this for unknown guardrail-id under wrong account
        }
        rate_codes = {"ThrottlingException", "TooManyRequestsException", "RequestLimitExceeded"}
        outage_codes = {"ServiceUnavailableException", "InternalServerException", "InternalServerError"}
        if code in auth_codes:
            return "auth_failed", http_status
        if code in rate_codes:
            return "rate_limited", http_status
        if code in outage_codes:
            return "upstream_outage", http_status
        if isinstance(http_status, int):
            return classify_http(http_status), http_status
    # Timeout-ish names that don't subclass cleanly
    name = type(e).__name__
    if "Timeout" in name or "ConnectError" in name:
        return "transport_error", None
    return "http_error", None


def _bedrock_client(cfg: Any):
    """Build a boto3 bedrock-runtime client from AppConfig fields. Returns None
    if boto3 isn't installed or required fields are missing."""
    try:
        import boto3  # type: ignore
    except ImportError:
        logger.error("boto3 not installed — Bedrock Guardrails provider unavailable")
        return None

    region = getattr(cfg, "bedrock_region", None) or "us-east-1"
    access_key = getattr(cfg, "bedrock_access_key_id", None)
    secret_key = getattr(cfg, "bedrock_secret_access_key", None)

    kwargs: Dict[str, Any] = {"region_name": region}
    if access_key and secret_key:
        kwargs["aws_access_key_id"] = access_key
        kwargs["aws_secret_access_key"] = secret_key
    # If keys are absent, boto3 falls back to the default credential chain
    # (env vars, instance profile, etc.) — useful for EC2 / ECS demos.

    try:
        return boto3.client("bedrock-runtime", **kwargs)
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to build Bedrock client: %s", e)
        return None


def _assemble_content(messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Bedrock's ApplyGuardrail expects a `content` list of text blocks. We
    pack the conversation in role-prefixed lines so all turns are evaluated."""
    lines: List[str] = []
    for m in messages:
        role = m.get("role", "user").upper()
        text = (m.get("content") or "").strip()
        if not text:
            continue
        lines.append(f"[{role}] {text}")
    blob = "\n\n".join(lines) if lines else ""
    return [{"text": {"text": blob}}] if blob else []


def _format_breakdown_from_assessment(
    assessment: Dict[str, Any], message_id: int
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()

    # Content policy
    for f in (assessment.get("contentPolicy") or {}).get("filters", []):
        t = _CONTENT_POLICY_MAP.get(f.get("type", ""))
        if t and t not in seen:
            seen.add(t)
            out.append({
                "project_id": None,
                "policy_id": "policy-bedrock-content",
                "detector_id": f"detector-bedrock-{f.get('type', 'unknown').lower()}",
                "detector_type": t,
                "detected": f.get("action", "").upper() in {"BLOCKED", "ANONYMIZED"},
                "message_id": message_id,
            })

    # Sensitive info / PII
    sens = assessment.get("sensitiveInformationPolicy") or {}
    for f in sens.get("piiEntities", []):
        t = _PII_MAP.get(f.get("type", ""))
        if t and t not in seen:
            seen.add(t)
            out.append({
                "project_id": None,
                "policy_id": "policy-bedrock-pii",
                "detector_id": f"detector-bedrock-{f.get('type', 'unknown').lower()}",
                "detector_type": t,
                "detected": f.get("action", "").upper() in {"BLOCKED", "ANONYMIZED"},
                "message_id": message_id,
            })
    for f in sens.get("regexes", []):
        if "pii/custom" not in seen:
            seen.add("pii/custom")
            out.append({
                "project_id": None,
                "policy_id": "policy-bedrock-pii",
                "detector_id": "detector-bedrock-regex",
                "detector_type": "pii/custom",
                "detected": f.get("action", "").upper() in {"BLOCKED", "ANONYMIZED"},
                "message_id": message_id,
            })

    # Denied topics
    for f in (assessment.get("topicPolicy") or {}).get("topics", []):
        key = f"moderated_content/topic-{f.get('name', 'unknown').lower()}"
        if key not in seen:
            seen.add(key)
            out.append({
                "project_id": None,
                "policy_id": "policy-bedrock-topic",
                "detector_id": f"detector-bedrock-topic-{f.get('name', 'unknown').lower()}",
                "detector_type": key,
                "detected": f.get("action", "").upper() == "BLOCKED",
                "message_id": message_id,
            })

    return out


class BedrockGuardrailsProvider(GuardrailProvider):
    id = "bedrock"
    display_name = "AWS Bedrock Guardrails"

    @classmethod
    def is_configured(cls, cfg: Any) -> bool:
        # Guardrail id is non-negotiable; AWS creds may come from env/role.
        return bool(getattr(cfg, "bedrock_guardrail_id", None))

    async def check_interaction(
        self,
        messages: List[Dict[str, str]],
        cfg: Any,
        meta: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
    ) -> Optional[GuardrailStatus]:
        guardrail_id = getattr(cfg, "bedrock_guardrail_id", None)
        guardrail_version = getattr(cfg, "bedrock_guardrail_version", None) or "DRAFT"
        if not guardrail_id:
            return None

        msgs = list(messages or [])
        if system_prompt and not any(m.get("role") == "system" for m in msgs):
            msgs.insert(0, {"role": "system", "content": system_prompt})

        content = _assemble_content(msgs)
        if not content:
            return None

        client = _bedrock_client(cfg)
        if not client:
            return make_error_status(self.id, "config_error", detail="boto3 unavailable or client build failed")

        # Decide INPUT vs OUTPUT — if the last message is from the assistant
        # this is a post-response check.
        source = "OUTPUT" if msgs and msgs[-1].get("role") == "assistant" else "INPUT"

        try:
            resp = client.apply_guardrail(
                guardrailIdentifier=guardrail_id,
                guardrailVersion=guardrail_version,
                source=source,
                content=content,
            )
        except Exception as e:  # noqa: BLE001
            error_class, http_status = _classify_botocore_exception(e)
            logger.warning("Bedrock ApplyGuardrail error (%s): %s", error_class, e)
            return make_error_status(self.id, error_class, http_status=http_status, detail=str(e))

        action = (resp.get("action") or "").upper()
        flagged = action in {"GUARDRAIL_INTERVENED"}
        assessments = resp.get("assessments") or []
        message_id = len(msgs) - 1 if msgs else 0
        breakdown: List[Dict[str, Any]] = []
        for assessment in assessments:
            breakdown.extend(_format_breakdown_from_assessment(assessment, message_id))

        status: GuardrailStatus = {
            "flagged": flagged or any(b.get("detected") for b in breakdown),
            "breakdown": breakdown,
            "payload": [],
            "metadata": {
                "source": "bedrock_guardrails",
                "guardrail_id": guardrail_id,
                "guardrail_version": guardrail_version,
                "action": action,
                "usage": resp.get("usage"),
            },
        }
        legacy_lakera.set_last_result(status)
        return status
