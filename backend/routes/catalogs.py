"""Read-only catalogs that drive Admin Console dropdowns.

These endpoints don't write to the DB — they just expose the static-ish
provider registry plus the dynamic model list for the active LLM provider.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import llm_client
from ..database import get_db
from ..guardrail_provider import list_providers_for_ui as list_guardrail_providers_for_ui
from ..models import AppConfig
from ..providers import list_providers_for_ui

router = APIRouter(prefix="/api", tags=["catalogs"])


@router.get("/models")
async def get_available_models(db: Session = Depends(get_db)):
    """Models available for the active provider (dynamic for proxy/Ollama, else static)."""
    config = db.query(AppConfig).first()
    try:
        models = llm_client.get_models(config)
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get models: {str(e)}") from e


def _augment_with_status(providers: list, cfg, kind: str) -> list:
    """Layer per-provider runtime state onto the static catalog:
    - `enabled`: not in cfg.disabled_providers (default True)
    - `is_active`: matches cfg.{llm,guardrail}_provider

    Used by both /api/providers and /api/guardrail-providers so the Admin
    Console can render a per-provider toggle/radio row without re-computing
    state client-side.
    """
    disabled = set((cfg.disabled_providers or []) if cfg else [])
    active_field = "llm_provider" if kind == "llm" else "guardrail_provider"
    active_id = getattr(cfg, active_field, None) if cfg else None
    out = []
    for p in providers:
        item = dict(p)
        item["enabled"] = p["id"] not in disabled
        item["is_active"] = (p["id"] == active_id)
        out.append(item)
    return out


@router.get("/providers")
async def get_providers(db: Session = Depends(get_db)):
    """Catalog of supported LLM providers for the Admin Console dropdown.
    Augmented with `enabled` (operator hasn't disabled it) + `is_active`
    (matches cfg.llm_provider).
    """
    cfg = db.query(AppConfig).first()
    return {"providers": _augment_with_status(list_providers_for_ui(), cfg, "llm")}


@router.get("/guardrail-providers")
async def get_guardrail_providers(db: Session = Depends(get_db)):
    """Catalog of supported guardrail providers (Lakera, OpenAI Moderation,
    Bedrock Guardrails, …) plus the per-provider AppConfig fields each one
    needs. Augmented with `enabled` + `is_active` runtime state.
    """
    cfg = db.query(AppConfig).first()
    return {"providers": _augment_with_status(list_guardrail_providers_for_ui(), cfg, "guardrail")}
