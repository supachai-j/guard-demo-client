"""One-click demo company switcher. Loads branding + system prompt +
curated demo prompts for the selected fake company so a salesperson can
flip between verticals mid-conversation."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import auth as _auth
from ..database import get_db
from ..models import AppConfig, DemoPrompt
from ..scenarios import SCENARIOS, get_scenario

router = APIRouter(prefix="/api", tags=["scenarios"])


# Fields exposed on GET /api/scenarios (preview / chooser UI). The system
# prompt + demo prompts are deliberately *not* in this list — they're large
# and only relevant on apply.
_SCENARIO_PREVIEW_FIELDS = (
    "id",
    "industry",
    "business_name",
    "tagline",
    "hero_text",
    "theme",
    "logo_url",
    "hero_image_url",
)


@router.get("/scenarios")
async def list_scenarios():
    """List available one-click demo scenarios (branding-level preview only)."""
    return {
        "scenarios": [
            {field: scenario.get(field) for field in _SCENARIO_PREVIEW_FIELDS}
            for scenario in SCENARIOS
        ]
    }


@router.post("/scenarios/{scenario_id}/apply", dependencies=[Depends(_auth.require_admin)])
async def apply_scenario(scenario_id: str, db: Session = Depends(get_db)):
    """Apply a scenario: update AppConfig branding/persona and replace demo prompts."""
    scenario = get_scenario(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")

    config = db.query(AppConfig).first()
    if not config:
        config = AppConfig()
        db.add(config)
        db.flush()

    config.business_name = scenario["business_name"]
    config.tagline = scenario["tagline"]
    config.hero_text = scenario["hero_text"]
    config.logo_url = scenario["logo_url"]
    config.hero_image_url = scenario["hero_image_url"]
    config.theme = scenario["theme"]
    config.system_prompt = scenario["system_prompt"]

    db.query(DemoPrompt).delete()
    for prompt in scenario.get("demo_prompts", []):
        db.add(
            DemoPrompt(
                title=prompt["title"],
                content=prompt["content"],
                category=prompt.get("category", "general"),
                tags=prompt.get("tags", []),
                is_malicious=prompt.get("is_malicious", False),
                preferred_llm=prompt.get("preferred_llm"),
            )
        )

    db.commit()
    return {
        "message": f"Scenario '{scenario_id}' applied",
        "scenario_id": scenario_id,
        "business_name": scenario["business_name"],
        "prompts_loaded": len(scenario.get("demo_prompts", [])),
    }
