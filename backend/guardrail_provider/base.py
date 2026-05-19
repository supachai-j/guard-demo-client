"""Abstract base + result shape for guardrail providers.

The unified result dict mirrors the Lakera /v2/guard response shape so the
existing frontend overlay (LakeraOverlay, CompareDialog) works for every
provider without changes. Adapters are responsible for normalising their
vendor response into this shape.

Failure handling — providers should NOT silently return None on HTTP /
transport errors; that collapses auth / rate-limit / outage / parse into one
indistinguishable null and forces the operator to guess. Use
`make_error_status` to return a structured empty status whose
`metadata.error` carries the classified cause; the playbook runner reads it
to produce an actionable histogram (e.g. "20 auth_failed (HTTP 403)" instead
of "20 null"). `flagged` stays False so chat-flow semantics are unchanged.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TypedDict


class GuardrailDetectorResult(TypedDict, total=False):
    """One row in `breakdown[]`. Mirrors Lakera's per-detector entry."""
    project_id: Optional[str]
    policy_id: Optional[str]
    detector_id: Optional[str]
    detector_type: str  # e.g. "prompt_attack", "pii/credit_card", "moderated_content/hate"
    detected: bool
    message_id: Optional[int]


class GuardrailStatus(TypedDict, total=False):
    """The Lakera-shaped result every provider must return."""
    flagged: bool
    breakdown: List[GuardrailDetectorResult]
    payload: List[Any]
    metadata: Dict[str, Any]


#: Stable set of error classes the playbook UI knows how to render.
#: Add new ones here when a provider needs a new bucket — keeping the list
#: small means the operator-facing histogram stays scannable.
ERROR_CLASSES = (
    "auth_failed",       # 401/403, bad/expired key, missing permission
    "rate_limited",      # 429, throttled
    "upstream_outage",   # 5xx, vendor degraded
    "transport_error",   # DNS, TCP, TLS, timeout — never reached vendor
    "parse_error",       # 2xx body unparseable
    "config_error",      # client built but mandatory field missing at call time
    "http_error",        # any other non-2xx
)


def classify_http(status_code: int) -> str:
    """Map an HTTP status code to one of ERROR_CLASSES."""
    if status_code in (401, 403):
        return "auth_failed"
    if status_code == 429:
        return "rate_limited"
    if 500 <= status_code < 600:
        return "upstream_outage"
    return "http_error"


def make_error_status(
    source: str,
    error_class: str,
    http_status: Optional[int] = None,
    detail: Optional[str] = None,
) -> GuardrailStatus:
    """Return an empty guardrail status tagged with a classified failure.

    `source` is the provider id (e.g. "palo_alto_airs"); `error_class` is one
    of ERROR_CLASSES. `flagged` stays False so chat-flow lets the turn
    through — preserving today's fail-open posture — but the playbook runner
    surfaces the classification to the operator.
    """
    meta: Dict[str, Any] = {"source": source, "error": error_class}
    if http_status is not None:
        meta["http_status"] = http_status
    if detail:
        meta["error_detail"] = str(detail)[:200]
    return {"flagged": False, "breakdown": [], "payload": [], "metadata": meta}


class GuardrailProvider(ABC):
    """Adapter interface for a third-party guardrail service.

    Implementations must be stateless except for vendor SDK clients they
    cache; the AppConfig row passed to `check_interaction` is the source of
    truth for keys, project IDs, regions, etc.
    """

    #: Identifier stored in AppConfig.guardrail_provider and used in the UI.
    id: str = ""

    #: Human-readable label for dropdowns.
    display_name: str = ""

    @classmethod
    @abstractmethod
    def is_configured(cls, cfg: Any) -> bool:
        """Whether the provider has enough config to make a call."""

    @abstractmethod
    async def check_interaction(
        self,
        messages: List[Dict[str, str]],
        cfg: Any,
        meta: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
    ) -> Optional[GuardrailStatus]:
        """Run the guardrail against the message turn.

        Returns the normalised Lakera-shaped status, or None on transient error.
        """

    #: Whether this provider can moderate images (override in subclasses).
    supports_image: bool = False

    async def check_image(
        self,
        image_data_url: str,
        cfg: Any,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[GuardrailStatus]:
        """Optional: moderate an image given as a `data:image/...;base64,...` URL.

        Default implementation returns a "not supported" status so callers can
        surface that to the UI without crashing.
        """
        return {
            "flagged": False,
            "breakdown": [],
            "payload": [],
            "metadata": {"source": self.id, "skipped": "image_moderation_not_supported"},
        }
