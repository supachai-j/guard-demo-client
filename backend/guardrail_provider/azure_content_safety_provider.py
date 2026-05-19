"""Azure AI Content Safety adapter.

Calls two endpoints in parallel:

1. POST {endpoint}/contentsafety/text:analyze
   Returns severity (0/2/4/6) per category — Hate / SelfHarm / Sexual / Violence.
2. POST {endpoint}/contentsafety/text:shieldPrompt
   Detects user-prompt-injection and document-attacks (returns boolean flags).

Both endpoints share auth (Ocp-Apim-Subscription-Key) and the same region
endpoint base. Severity ≥ 4 maps to "detected" by default — this is the
"Medium" threshold Azure recommends for moderate filtering.

Docs:
- https://learn.microsoft.com/en-us/azure/ai-services/content-safety/quickstart-text
- https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/jailbreak-detection
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from .. import lakera as legacy_lakera
from .base import GuardrailProvider, GuardrailStatus, classify_http, make_error_status

logger = logging.getLogger(__name__)


_API_VERSION = "2024-09-01"
_DEFAULT_SEVERITY_THRESHOLD = 4  # Medium and above counts as "detected"

# Azure category → our detector_type taxonomy
_CATEGORY_MAP = {
    "Hate": "moderated_content/hate",
    "SelfHarm": "moderated_content/crime",
    "Sexual": "moderated_content/sexual",
    "Violence": "moderated_content/violence",
}


def _flatten_text(messages: List[Dict[str, str]]) -> str:
    parts: List[str] = []
    for m in messages:
        role = m.get("role", "user").upper()
        content = (m.get("content") or "").strip()
        if not content:
            continue
        parts.append(f"[{role}] {content}")
    return "\n\n".join(parts)


def _last_user_text(messages: List[Dict[str, str]]) -> str:
    """Prompt-shield endpoint scans the user prompt specifically."""
    for m in reversed(messages):
        if m.get("role") == "user" and m.get("content"):
            return m["content"]
    # fall back to whole concatenation if no user turn
    return _flatten_text(messages)


def _format_categories(
    categories: List[Dict[str, Any]],
    message_id: int,
    threshold: int = _DEFAULT_SEVERITY_THRESHOLD,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for entry in categories or []:
        cat = entry.get("category")
        sev = entry.get("severity", 0)
        detector_type = _CATEGORY_MAP.get(cat)
        if not detector_type:
            continue
        out.append({
            "project_id": None,
            "policy_id": "policy-azure-content-safety",
            "detector_id": f"detector-azure-{cat.lower()}",
            "detector_type": detector_type,
            "detected": isinstance(sev, int) and sev >= threshold,
            "message_id": message_id,
            "severity": sev,
        })
    return out


def _format_shield(
    shield_result: Optional[Dict[str, Any]], message_id: int
) -> List[Dict[str, Any]]:
    """Translate Prompt Shields response into prompt_attack rows."""
    if not isinstance(shield_result, dict):
        return []
    out: List[Dict[str, Any]] = []
    user_analysis = shield_result.get("userPromptAnalysis") or {}
    if user_analysis.get("attackDetected"):
        out.append({
            "project_id": None,
            "policy_id": "policy-azure-prompt-shield",
            "detector_id": "detector-azure-user-prompt-attack",
            "detector_type": "prompt_attack",
            "detected": True,
            "message_id": message_id,
        })
    for doc in shield_result.get("documentsAnalysis") or []:
        if isinstance(doc, dict) and doc.get("attackDetected"):
            out.append({
                "project_id": None,
                "policy_id": "policy-azure-prompt-shield",
                "detector_id": "detector-azure-document-attack",
                "detector_type": "prompt_attack",
                "detected": True,
                "message_id": message_id,
            })
            break  # one row per turn is enough
    return out


class AzureContentSafetyProvider(GuardrailProvider):
    id = "azure_content_safety"
    display_name = "Azure AI Content Safety"
    supports_image = True

    @classmethod
    def is_configured(cls, cfg: Any) -> bool:
        return bool(
            getattr(cfg, "azure_content_safety_endpoint", None)
            and getattr(cfg, "azure_content_safety_key", None)
        )

    async def check_interaction(
        self,
        messages: List[Dict[str, str]],
        cfg: Any,
        meta: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
    ) -> Optional[GuardrailStatus]:
        endpoint = (getattr(cfg, "azure_content_safety_endpoint", None) or "").rstrip("/")
        key = getattr(cfg, "azure_content_safety_key", None)
        if not endpoint or not key:
            return None

        msgs = list(messages or [])
        if system_prompt and not any(m.get("role") == "system" for m in msgs):
            msgs.insert(0, {"role": "system", "content": system_prompt})

        analyze_text = _flatten_text(msgs)
        shield_text = _last_user_text(msgs)
        if not analyze_text and not shield_text:
            return None

        headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/json",
        }
        message_id = len(msgs) - 1 if msgs else 0

        analyze_url = f"{endpoint}/contentsafety/text:analyze?api-version={_API_VERSION}"
        shield_url = f"{endpoint}/contentsafety/text:shieldPrompt?api-version={_API_VERSION}"

        analyze_body = {
            "text": analyze_text,
            "outputType": "FourSeverityLevels",
        }
        shield_body = {
            "userPrompt": shield_text,
            "documents": [],
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                results = await asyncio.gather(
                    client.post(analyze_url, headers=headers, json=analyze_body),
                    client.post(shield_url, headers=headers, json=shield_body),
                    return_exceptions=True,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("Azure Content Safety transport error: %s", e)
            return make_error_status(self.id, "transport_error", detail=str(e))

        analyze_resp, shield_resp = results
        breakdown: List[Dict[str, Any]] = []
        # Track which upstream calls produced usable data. If neither did, we
        # must NOT pretend the prompt is clean — the caller (compare panel,
        # chat path) needs to know the check effectively didn't run.
        analyze_ok = False
        shield_ok = False
        # Treat 404 on shieldPrompt as "endpoint not available" rather than failure;
        # we still want to count the partial outage as informational.
        shield_unavailable = False
        partial_failure: List[str] = []
        # Capture the dominant error class so a total-failure (neither call
        # produced usable data) can surface auth_failed / rate_limited /
        # upstream_outage to the playbook UI instead of an opaque null.
        dominant_error: Optional[str] = None
        dominant_status: Optional[int] = None
        def _record(err_class: str, http_status: Optional[int] = None) -> None:
            nonlocal dominant_error, dominant_status
            # First non-transport error wins; auth_failed beats anything else.
            if dominant_error is None or err_class == "auth_failed":
                dominant_error = err_class
                dominant_status = http_status

        # text:analyze categories
        if isinstance(analyze_resp, httpx.Response):
            if analyze_resp.status_code < 400:
                try:
                    data = analyze_resp.json()
                    breakdown.extend(
                        _format_categories(data.get("categoriesAnalysis") or [], message_id)
                    )
                    analyze_ok = True
                except Exception as e:  # noqa: BLE001
                    logger.warning("Azure text:analyze parse error: %s", e)
                    partial_failure.append(f"text:analyze parse error: {e}")
                    _record("parse_error")
            else:
                logger.warning(
                    "Azure text:analyze HTTP %s: %s",
                    analyze_resp.status_code,
                    analyze_resp.text[:200],
                )
                partial_failure.append(f"text:analyze HTTP {analyze_resp.status_code}")
                _record(classify_http(analyze_resp.status_code), analyze_resp.status_code)
        elif isinstance(analyze_resp, Exception):
            logger.warning("Azure text:analyze failed: %s", analyze_resp)
            partial_failure.append(f"text:analyze transport error: {analyze_resp}")
            _record("transport_error")

        # text:shieldPrompt — may not be available in older API versions; ignore on 404.
        if isinstance(shield_resp, httpx.Response):
            if shield_resp.status_code < 400:
                try:
                    data = shield_resp.json()
                    breakdown.extend(_format_shield(data, message_id))
                    shield_ok = True
                except Exception as e:  # noqa: BLE001
                    logger.warning("Azure shieldPrompt parse error: %s", e)
                    partial_failure.append(f"shieldPrompt parse error: {e}")
                    _record("parse_error")
            elif shield_resp.status_code == 404:
                logger.info("Azure Prompt Shields not available in this region/api-version")
                shield_unavailable = True  # not counted as a failure
            else:
                logger.warning(
                    "Azure shieldPrompt HTTP %s: %s",
                    shield_resp.status_code,
                    shield_resp.text[:200],
                )
                partial_failure.append(f"shieldPrompt HTTP {shield_resp.status_code}")
                _record(classify_http(shield_resp.status_code), shield_resp.status_code)
        elif isinstance(shield_resp, Exception):
            logger.warning("Azure shieldPrompt failed: %s", shield_resp)
            partial_failure.append(f"shieldPrompt transport error: {shield_resp}")
            _record("transport_error")

        # No usable data at all? Return a classified error-status so the
        # playbook UI can surface auth_failed / rate_limited / outage instead
        # of an opaque null. Without this, Azure was silently fail-open: a
        # DNS or 401 failure produced `flagged=False` and the chat path would
        # let an attack through.
        if not analyze_ok and not shield_ok and not shield_unavailable:
            return make_error_status(
                self.id,
                dominant_error or "http_error",
                http_status=dominant_status,
                detail="; ".join(partial_failure) if partial_failure else None,
            )

        flagged = any(b.get("detected") for b in breakdown)

        metadata: Dict[str, Any] = {
            "source": "azure_content_safety",
            "endpoint": endpoint,
            "api_version": _API_VERSION,
        }
        if partial_failure:
            metadata["partial_failure"] = partial_failure

        status: GuardrailStatus = {
            "flagged": flagged,
            "breakdown": breakdown,
            "payload": [],
            "metadata": metadata,
        }
        legacy_lakera.set_last_result(status)
        return status

    async def check_image(
        self,
        image_data_url: str,
        cfg: Any,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[GuardrailStatus]:
        """Azure image:analyze accepts base64 content (no data: prefix)."""
        endpoint = (getattr(cfg, "azure_content_safety_endpoint", None) or "").rstrip("/")
        key = getattr(cfg, "azure_content_safety_key", None)
        if not endpoint or not key or not image_data_url:
            return None

        # Strip "data:image/png;base64," prefix if present
        b64 = image_data_url
        if "," in b64 and b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]

        headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/json",
        }
        url = f"{endpoint}/contentsafety/image:analyze?api-version={_API_VERSION}"
        body = {
            "image": {"content": b64},
            "outputType": "FourSeverityLevels",
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, headers=headers, json=body)
        except Exception as e:  # noqa: BLE001
            logger.warning("Azure image:analyze transport error: %s", e)
            return make_error_status(self.id, "transport_error", detail=str(e))

        if resp.status_code >= 400:
            error_class = classify_http(resp.status_code)
            logger.warning("Azure image:analyze HTTP %s (%s): %s", resp.status_code, error_class, resp.text[:200])
            return make_error_status(self.id, error_class, http_status=resp.status_code, detail=resp.text)

        try:
            data = resp.json()
        except Exception as e:
            return make_error_status(self.id, "parse_error", detail=str(e))

        breakdown = _format_categories(data.get("categoriesAnalysis") or [], message_id=0)
        flagged = any(b.get("detected") for b in breakdown)
        status: GuardrailStatus = {
            "flagged": flagged,
            "breakdown": breakdown,
            "payload": [],
            "metadata": {
                "source": "azure_content_safety",
                "kind": "image",
                "api_version": _API_VERSION,
            },
        }
        legacy_lakera.set_last_result(status)
        return status
