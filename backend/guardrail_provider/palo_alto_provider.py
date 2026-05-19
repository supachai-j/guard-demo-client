"""Palo Alto Prisma AIRS (AI Runtime Security) adapter.

Calls POST /v1/scan/sync/request on the regional AIRS host. Auth is the
`x-pan-token` header. Maps Palo Alto's per-detector boolean flags
(prompt_detected.injection / dlp / url_cats / toxic_content / malicious_code)
into our shared detector_type taxonomy.

Docs:
- https://pan.dev/prisma-airs/api/airuntimesecurity/
- https://pan.dev/prisma-airs/api/airuntimesecurity/scan/scan-sync-request/

Regional hosts:
- US:  service.api.aisecurity.paloaltonetworks.com
- EU:  service-de.api.aisecurity.paloaltonetworks.com
- IN:  service-in.api.aisecurity.paloaltonetworks.com
- SG:  service-sg.api.aisecurity.paloaltonetworks.com

Request shape (per doc examples):
{
  "tr_id": "...",
  "ai_profile": { "profile_name": "..." },
  "metadata": { "app_user": "...", "ai_model": "..." },
  "contents": [ { "prompt": "..." } or { "response": "..." } ]
}

Response shape:
{
  "action": "block" | "allow",
  "category": "malicious" | "benign",
  "prompt_detected": { "injection": bool, "dlp": bool, "url_cats": bool, ... },
  "response_detected": { ... },
  "scan_id": "...", "report_id": "...", "tr_id": "..."
}
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

from .. import lakera as legacy_lakera
from .base import GuardrailProvider, GuardrailStatus, classify_http, make_error_status

logger = logging.getLogger(__name__)


_DEFAULT_HOST = "service-sg.api.aisecurity.paloaltonetworks.com"

# Palo Alto detector flag → our shared detector_type
_DETECTOR_MAP = {
    "injection": "prompt_attack",
    "dlp": "pii/custom",
    "url_cats": "unknown_links",
    "toxic_content": "moderated_content/violence",
    "malicious_code": "moderated_content/crime",
    # The API may return additional flags (agent, hallucination, etc.) — we
    # forward those under a generic moderated_content/* prefix without losing
    # the original name.
}


def _detector_type_for_flag(flag_name: str) -> str:
    if flag_name in _DETECTOR_MAP:
        return _DETECTOR_MAP[flag_name]
    return f"moderated_content/{flag_name}"


def _last_user_text(messages: List[Dict[str, str]]) -> Optional[str]:
    for m in reversed(messages):
        if m.get("role") == "user" and m.get("content"):
            return m["content"]
    return None


def _last_assistant_text(messages: List[Dict[str, str]]) -> Optional[str]:
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            return m["content"]
    return None


def _format_breakdown(
    detected: Dict[str, Any], message_id: int, location: str
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for flag, value in (detected or {}).items():
        if not value:
            continue
        out.append({
            "project_id": None,
            "policy_id": f"policy-palo-alto-{location}",
            "detector_id": f"detector-palo-alto-{location}-{flag}",
            "detector_type": _detector_type_for_flag(flag),
            "detected": True,
            "message_id": message_id,
        })
    return out


class PaloAltoAirsProvider(GuardrailProvider):
    id = "palo_alto_airs"
    display_name = "Palo Alto Prisma AIRS"

    @classmethod
    def is_configured(cls, cfg: Any) -> bool:
        return bool(
            getattr(cfg, "palo_alto_api_key", None)
            and getattr(cfg, "palo_alto_profile_name", None)
        )

    async def check_interaction(
        self,
        messages: List[Dict[str, str]],
        cfg: Any,
        meta: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
    ) -> Optional[GuardrailStatus]:
        api_key = getattr(cfg, "palo_alto_api_key", None)
        profile_name = getattr(cfg, "palo_alto_profile_name", None)
        host = (getattr(cfg, "palo_alto_host", None) or _DEFAULT_HOST).strip()
        if not api_key or not profile_name:
            return None
        if host.startswith("http://") or host.startswith("https://"):
            base = host.rstrip("/")
        else:
            base = f"https://{host.rstrip('/')}"

        msgs = list(messages or [])
        user_text = _last_user_text(msgs)
        assistant_text = _last_assistant_text(msgs)

        contents: List[Dict[str, Any]] = []
        if user_text:
            contents.append({"prompt": user_text})
        if assistant_text:
            contents.append({"response": assistant_text})
        if not contents:
            return None

        tr_id = (meta or {}).get("session_id") or "guard-demo-client"

        body: Dict[str, Any] = {
            "tr_id": str(tr_id),
            "ai_profile": {"profile_name": profile_name},
            "metadata": {
                "app_user": (meta or {}).get("user_id") or "guard-demo-client",
                "ai_model": getattr(cfg, "openai_model", "unknown"),
            },
            "contents": contents,
        }

        headers = {
            "x-pan-token": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        url = f"{base}/v1/scan/sync/request"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, headers=headers, json=body)
        except Exception as e:  # noqa: BLE001
            logger.warning("Palo Alto AIRS transport error: %s", e)
            return make_error_status(self.id, "transport_error", detail=str(e))

        if resp.status_code >= 400:
            error_class = classify_http(resp.status_code)
            logger.warning(
                "Palo Alto AIRS HTTP %s (%s): %s",
                resp.status_code, error_class, resp.text[:200],
            )
            return make_error_status(self.id, error_class, http_status=resp.status_code, detail=resp.text)

        try:
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            logger.warning("Palo Alto AIRS parse error: %s", e)
            return make_error_status(self.id, "parse_error", detail=str(e))

        action = (data.get("action") or "").lower()
        category = (data.get("category") or "").lower()
        prompt_detected = data.get("prompt_detected") or {}
        response_detected = data.get("response_detected") or {}

        user_msg_id = next(
            (i for i, m in enumerate(msgs) if m.get("role") == "user"),
            0,
        )
        assistant_msg_id = next(
            (i for i, m in enumerate(msgs) if m.get("role") == "assistant"),
            len(msgs) - 1 if msgs else 0,
        )

        breakdown: List[Dict[str, Any]] = []
        breakdown.extend(_format_breakdown(prompt_detected, user_msg_id, "prompt"))
        breakdown.extend(_format_breakdown(response_detected, assistant_msg_id, "response"))

        flagged = action == "block" or category == "malicious" or any(
            b.get("detected") for b in breakdown
        )

        status: GuardrailStatus = {
            "flagged": flagged,
            "breakdown": breakdown,
            "payload": [],
            "metadata": {
                "source": "palo_alto_airs",
                "action": action,
                "category": category,
                "scan_id": data.get("scan_id"),
                "report_id": data.get("report_id"),
                "tr_id": data.get("tr_id"),
                "profile_name": data.get("profile_name"),
            },
        }
        legacy_lakera.set_last_result(status)
        return status
