"""Demo prompt corpus — the curated library of prompts the chat widget's
autocomplete pulls from. Per-scenario corpora get loaded on
POST /api/scenarios/{id}/apply (see routes.scenarios)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import auth as _auth
from ..database import get_db
from ..models import DemoPrompt
from ..schemas import DemoPromptCreate, DemoPromptResponse, DemoPromptUpdate

router = APIRouter(prefix="/api/demo-prompts", tags=["demo-prompts"])


@router.get("", response_model=List[DemoPromptResponse])
async def get_demo_prompts(category: Optional[str] = None, limit: int = 50, db: Session = Depends(get_db)):
    """Get all demo prompts, optionally filtered by category"""
    query = db.query(DemoPrompt)

    if category:
        query = query.filter(DemoPrompt.category == category)

    prompts = query.order_by(DemoPrompt.usage_count.desc(), DemoPrompt.created_at.desc()).limit(limit).all()
    return prompts


@router.get("/search")
async def search_demo_prompts(q: str, category: Optional[str] = None, limit: int = 10, db: Session = Depends(get_db)):
    """Search demo prompts by title, content, or tags"""
    if not q or len(q.strip()) < 2:
        return {"prompts": [], "suggestions": []}

    query = q.strip().lower()

    # Search in title, content, and tags
    prompts = db.query(DemoPrompt).filter(
        (DemoPrompt.title.ilike(f"%{query}%"))
        | (DemoPrompt.content.ilike(f"%{query}%"))
        | (DemoPrompt.tags.contains([query]))
    )

    if category:
        prompts = prompts.filter(DemoPrompt.category == category)

    results = prompts.order_by(DemoPrompt.usage_count.desc()).limit(limit).all()

    # Generate suggestions for autocomplete
    suggestions = []
    for prompt in results:
        # Find the best matching part for autocomplete
        title_lower = prompt.title.lower()
        content_lower = prompt.content.lower()

        if query in title_lower:
            # Use title for autocomplete
            start_idx = title_lower.find(query)
            suggestion = prompt.title[start_idx : start_idx + len(query) + 20]  # Show more context
            suggestions.append(
                {
                    "text": suggestion,
                    "full_content": prompt.content,
                    "title": prompt.title,
                    "category": prompt.category,
                    "is_malicious": prompt.is_malicious,
                    "prompt_id": prompt.id,
                    "preferred_llm": getattr(prompt, "preferred_llm", None),
                }
            )
        elif query in content_lower:
            # Use content for autocomplete
            start_idx = content_lower.find(query)
            suggestion = prompt.content[start_idx : start_idx + len(query) + 20]
            suggestions.append(
                {
                    "text": suggestion,
                    "full_content": prompt.content,
                    "title": prompt.title,
                    "category": prompt.category,
                    "is_malicious": prompt.is_malicious,
                    "prompt_id": prompt.id,
                    "preferred_llm": getattr(prompt, "preferred_llm", None),
                }
            )

    return {
        "prompts": [
            {
                "id": prompt.id,
                "title": prompt.title,
                "content": prompt.content,
                "category": prompt.category,
                "tags": prompt.tags,
                "is_malicious": prompt.is_malicious,
                "usage_count": prompt.usage_count,
                "preferred_llm": getattr(prompt, "preferred_llm", None),
            }
            for prompt in results
        ],
        "suggestions": suggestions[:5],  # Limit to top 5 suggestions
    }


@router.post("", response_model=DemoPromptResponse, dependencies=[Depends(_auth.require_admin)])
async def create_demo_prompt(prompt: DemoPromptCreate, db: Session = Depends(get_db)):
    """Create a new demo prompt"""
    db_prompt = DemoPrompt(**prompt.dict())
    db.add(db_prompt)
    db.commit()
    db.refresh(db_prompt)
    return db_prompt


@router.put("/{prompt_id}", response_model=DemoPromptResponse, dependencies=[Depends(_auth.require_admin)])
async def update_demo_prompt(prompt_id: int, prompt: DemoPromptUpdate, db: Session = Depends(get_db)):
    """Update an existing demo prompt"""
    db_prompt = db.query(DemoPrompt).filter(DemoPrompt.id == prompt_id).first()
    if not db_prompt:
        raise HTTPException(status_code=404, detail="Demo prompt not found")

    for field, value in prompt.dict(exclude_unset=True).items():
        setattr(db_prompt, field, value)

    db.commit()
    db.refresh(db_prompt)
    return db_prompt


@router.delete("/{prompt_id}", dependencies=[Depends(_auth.require_admin)])
async def delete_demo_prompt(prompt_id: int, db: Session = Depends(get_db)):
    """Delete a demo prompt"""
    db_prompt = db.query(DemoPrompt).filter(DemoPrompt.id == prompt_id).first()
    if not db_prompt:
        raise HTTPException(status_code=404, detail="Demo prompt not found")

    db.delete(db_prompt)
    db.commit()
    return {"message": "Demo prompt deleted"}


@router.post("/{prompt_id}/use")
async def use_demo_prompt(prompt_id: int, db: Session = Depends(get_db)):
    """Increment usage count for a demo prompt"""
    db_prompt = db.query(DemoPrompt).filter(DemoPrompt.id == prompt_id).first()
    if not db_prompt:
        raise HTTPException(status_code=404, detail="Demo prompt not found")

    db_prompt.usage_count += 1
    db.commit()
    return {"message": "Usage count updated", "usage_count": db_prompt.usage_count}
