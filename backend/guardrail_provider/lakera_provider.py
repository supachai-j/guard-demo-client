"""Lakera Guard adapter — thin wrapper around the existing backend/lakera.py.

The legacy module keeps its public surface (callers like agent.py and main.py
still import set_last_result / get_last_result / get_last_request from it),
this adapter just gives Lakera the same interface the other providers expose.
"""

from typing import Any, Dict, List, Optional

from .. import lakera as legacy_lakera
from .base import GuardrailProvider, GuardrailStatus


class LakeraProvider(GuardrailProvider):
    id = "lakera"
    display_name = "Lakera Guard"

    @classmethod
    def is_configured(cls, cfg: Any) -> bool:
        return bool(getattr(cfg, "lakera_api_key", None))

    async def check_interaction(
        self,
        messages: List[Dict[str, str]],
        cfg: Any,
        meta: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
    ) -> Optional[GuardrailStatus]:
        return await legacy_lakera.check_interaction(
            messages=messages,
            meta=meta,
            api_key=getattr(cfg, "lakera_api_key", None),
            project_id=getattr(cfg, "lakera_project_id", None),
            system_prompt=system_prompt,
        )
