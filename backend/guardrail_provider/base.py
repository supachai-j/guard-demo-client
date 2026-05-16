"""Abstract base + result shape for guardrail providers.

The unified result dict mirrors the Lakera /v2/guard response shape so the
existing frontend overlay (LakeraOverlay, CompareDialog) works for every
provider without changes. Adapters are responsible for normalising their
vendor response into this shape.
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
