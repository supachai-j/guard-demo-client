"""OpenAI Moderation API adapter.

Uses /v1/moderations (free of charge with an OpenAI key) and maps the
`omni-moderation-latest` category set to our `moderated_content/*` taxonomy
so the same UI badges work.

Note: OpenAI Moderation does NOT have a prompt-injection class — for that
detector type, customers should use Lakera or Bedrock prompt-attack.
"""

import logging
from typing import Any, Dict, List, Optional

from openai import OpenAI

from .. import lakera as legacy_lakera
from .base import GuardrailProvider, GuardrailStatus, classify_http, make_error_status

logger = logging.getLogger(__name__)


# Map OpenAI's category keys to our existing moderated_content/* labels so
# the frontend's DETECTOR_LABELS dict picks them up without a code change.
_CATEGORY_MAP = {
    "hate": "moderated_content/hate",
    "hate/threatening": "moderated_content/hate",
    "harassment": "moderated_content/hate",
    "harassment/threatening": "moderated_content/violence",
    "sexual": "moderated_content/sexual",
    "sexual/minors": "moderated_content/sexual",
    "violence": "moderated_content/violence",
    "violence/graphic": "moderated_content/violence",
    "self-harm": "moderated_content/crime",
    "self-harm/intent": "moderated_content/crime",
    "self-harm/instructions": "moderated_content/crime",
    "illicit": "moderated_content/crime",
    "illicit/violent": "moderated_content/weapons",
}


def _classify_openai_exception(e: Exception) -> str:
    """Map an `openai` SDK exception (or any exception) to a base error class.

    Imports are lazy so we never crash on a missing/older SDK; we just fall
    through to the HTTP-status fallback or transport_error.
    """
    try:
        import openai as _openai
        if isinstance(e, getattr(_openai, "AuthenticationError", ())):
            return "auth_failed"
        if isinstance(e, getattr(_openai, "PermissionDeniedError", ())):
            return "auth_failed"
        if isinstance(e, getattr(_openai, "RateLimitError", ())):
            return "rate_limited"
        if isinstance(e, getattr(_openai, "APIConnectionError", ())):
            return "transport_error"
        if isinstance(e, getattr(_openai, "APITimeoutError", ())):
            return "transport_error"
        if isinstance(e, getattr(_openai, "APIStatusError", ())):
            sc = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
            return classify_http(sc) if isinstance(sc, int) else "http_error"
    except Exception:
        pass
    sc = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    if isinstance(sc, int):
        return classify_http(sc)
    return "transport_error"


def _last_user_text(messages: List[Dict[str, str]]) -> str:
    """OpenAI moderation accepts a single string; pick the last user turn,
    falling back to the last message of any role."""
    for m in reversed(messages):
        if m.get("role") == "user" and m.get("content"):
            return m["content"]
    for m in reversed(messages):
        if m.get("content"):
            return m["content"]
    return ""


def _format_breakdown(categories: Dict[str, Any], message_id: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen_types: set[str] = set()
    for cat, flagged in (categories or {}).items():
        if not flagged:
            continue
        detector_type = _CATEGORY_MAP.get(cat)
        if not detector_type or detector_type in seen_types:
            continue
        seen_types.add(detector_type)
        out.append(
            {
                "project_id": None,
                "policy_id": "policy-openai-moderation",
                "detector_id": f"detector-openai-{cat.replace('/', '-')}",
                "detector_type": detector_type,
                "detected": True,
                "message_id": message_id,
            }
        )
    return out


class OpenAIModerationProvider(GuardrailProvider):
    id = "openai_moderation"
    display_name = "OpenAI Moderation"
    supports_image = True

    @classmethod
    def is_configured(cls, cfg: Any) -> bool:
        return bool(getattr(cfg, "openai_api_key", None))

    async def check_interaction(
        self,
        messages: List[Dict[str, str]],
        cfg: Any,
        meta: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
    ) -> Optional[GuardrailStatus]:
        api_key = getattr(cfg, "openai_api_key", None)
        if not api_key:
            return None

        text = _last_user_text(messages)
        if not text:
            empty: GuardrailStatus = {
                "flagged": False,
                "breakdown": [],
                "payload": [],
                "metadata": {"source": "openai_moderation", "skipped": "empty_messages"},
            }
            legacy_lakera.set_last_result(empty)
            return empty

        # The user/assistant index of the message we scanned (Lakera convention:
        # 0 = system, 1 = user, 2 = assistant, …).  We approximate with the
        # role of the last content-bearing message.
        message_id = 0
        if any(m.get("role") == "system" for m in messages):
            message_id = 1 if any(m.get("role") == "user" for m in messages) else 0

        try:
            client = OpenAI(api_key=api_key)
            resp = client.moderations.create(
                model="omni-moderation-latest",
                input=text,
            )
        except Exception as e:  # noqa: BLE001 — vendor SDK throws many shapes
            error_class = _classify_openai_exception(e)
            http_status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
            logger.warning("OpenAI Moderation error (%s): %s", error_class, e)
            return make_error_status(self.id, error_class, http_status=http_status, detail=str(e))

        # The OpenAI SDK returns a Pydantic-ish object; .results[0].categories
        # is a dict-like with bool flags.
        result_obj = (resp.results or [None])[0]
        if result_obj is None:
            return make_error_status(self.id, "parse_error", detail="empty results array")

        try:
            categories = result_obj.categories.model_dump()  # type: ignore[attr-defined]
        except AttributeError:
            categories = dict(getattr(result_obj, "categories", {}) or {})

        flagged = bool(getattr(result_obj, "flagged", False))
        breakdown = _format_breakdown(categories, message_id=message_id)

        status: GuardrailStatus = {
            "flagged": flagged,
            "breakdown": breakdown,
            "payload": [],
            "metadata": {
                "source": "openai_moderation",
                "model": getattr(resp, "model", "omni-moderation-latest"),
                "request_uuid": getattr(resp, "id", None),
            },
        }
        legacy_lakera.set_last_result(status)
        return status

    async def check_image(
        self,
        image_data_url: str,
        cfg: Any,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[GuardrailStatus]:
        api_key = getattr(cfg, "openai_api_key", None)
        if not api_key:
            return None
        try:
            client = OpenAI(api_key=api_key)
            # omni-moderation-latest accepts multimodal inputs via the array form.
            resp = client.moderations.create(
                model="omni-moderation-latest",
                input=[{"type": "image_url", "image_url": {"url": image_data_url}}],
            )
        except Exception as e:  # noqa: BLE001
            error_class = _classify_openai_exception(e)
            http_status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
            logger.warning("OpenAI Moderation image check error (%s): %s", error_class, e)
            return make_error_status(self.id, error_class, http_status=http_status, detail=str(e))

        result_obj = (resp.results or [None])[0]
        if result_obj is None:
            return make_error_status(self.id, "parse_error", detail="empty results array")
        try:
            categories = result_obj.categories.model_dump()  # type: ignore[attr-defined]
        except AttributeError:
            categories = dict(getattr(result_obj, "categories", {}) or {})

        flagged = bool(getattr(result_obj, "flagged", False))
        breakdown = _format_breakdown(categories, message_id=0)
        status: GuardrailStatus = {
            "flagged": flagged,
            "breakdown": breakdown,
            "payload": [],
            "metadata": {
                "source": "openai_moderation",
                "model": getattr(resp, "model", "omni-moderation-latest"),
                "kind": "image",
            },
        }
        legacy_lakera.set_last_result(status)
        return status
