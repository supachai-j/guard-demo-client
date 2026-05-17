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


@router.get("/providers")
async def get_providers():
    """Catalog of supported LLM providers for the Admin Console dropdown."""
    return {"providers": list_providers_for_ui()}


@router.get("/guardrail-providers")
async def get_guardrail_providers():
    """Catalog of supported guardrail providers (Lakera, OpenAI Moderation,
    Bedrock Guardrails, …) plus the per-provider AppConfig fields each one
    needs."""
    return {"providers": list_guardrail_providers_for_ui()}
