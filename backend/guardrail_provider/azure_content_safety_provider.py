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
from .base import GuardrailProvider, GuardrailStatus

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
            return None

        analyze_resp, shield_resp = results
        breakdown: List[Dict[str, Any]] = []

        # text:analyze categories
        if isinstance(analyze_resp, httpx.Response):
            if analyze_resp.status_code < 400:
                try:
                    data = analyze_resp.json()
                    breakdown.extend(
                        _format_categories(data.get("categoriesAnalysis") or [], message_id)
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning("Azure text:analyze parse error: %s", e)
            else:
                logger.warning(
                    "Azure text:analyze HTTP %s: %s",
                    analyze_resp.status_code,
                    analyze_resp.text[:200],
                )
        elif isinstance(analyze_resp, Exception):
            logger.warning("Azure text:analyze failed: %s", analyze_resp)

        # text:shieldPrompt — may not be available in older API versions; ignore on 404.
        if isinstance(shield_resp, httpx.Response):
            if shield_resp.status_code < 400:
                try:
                    data = shield_resp.json()
                    breakdown.extend(_format_shield(data, message_id))
                except Exception as e:  # noqa: BLE001
                    logger.warning("Azure shieldPrompt parse error: %s", e)
            elif shield_resp.status_code == 404:
                logger.info("Azure Prompt Shields not available in this region/api-version")
            else:
                logger.warning(
                    "Azure shieldPrompt HTTP %s: %s",
                    shield_resp.status_code,
                    shield_resp.text[:200],
                )
        elif isinstance(shield_resp, Exception):
            logger.warning("Azure shieldPrompt failed: %s", shield_resp)

        flagged = any(b.get("detected") for b in breakdown)

        status: GuardrailStatus = {
            "flagged": flagged,
            "breakdown": breakdown,
            "payload": [],
            "metadata": {
                "source": "azure_content_safety",
                "endpoint": endpoint,
                "api_version": _API_VERSION,
            },
        }
        legacy_lakera.set_last_result(status)
        return status
