"""Playbook endpoints — predefined attack suites (OWASP LLM Top 10,
POC verification) plus customer-specific custom playbooks stored
in the playbooks table. Built-ins live in backend/playbooks.py and
are merged in for GET; PUT/DELETE on a built-in id returns 403."""

import asyncio
import re
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import auth as _auth
from .. import playbooks as _playbooks
from ..database import get_db
from ..models import AppConfig, Playbook, PlaybookRun
from ..schemas import PlaybookCreate, PlaybookUpdate

router = APIRouter(prefix="/api/playbooks", tags=["playbooks"])


def _slugify(name: str) -> str:
    """Convert a human name into a URL-safe playbook slug."""
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return slug or "playbook"


def _unique_slug(db: Session, name: str) -> str:
    """Generate a slug unique across both built-ins and the DB."""
    base = _slugify(name)
    candidate = base
    suffix = 2
    while _playbooks.is_builtin(candidate) or db.query(Playbook).filter(Playbook.slug == candidate).first():
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def _custom_playbook_to_dict(pb: Playbook) -> Dict:
    return {
        "id": pb.slug,
        "name": pb.name,
        "description": pb.description,
        "docs_url": None,
        "prompts": pb.prompts or [],
        "is_builtin": False,
        "created_at": pb.created_at.isoformat() if pb.created_at else None,
        "updated_at": pb.updated_at.isoformat() if pb.updated_at else None,
    }


def _resolve_playbook(db: Session, playbook_id: str) -> Optional[Dict]:
    """Find a playbook by id — built-in first, then DB by slug."""
    pb = _playbooks.get_playbook(playbook_id)
    if pb:
        return {**pb, "is_builtin": True}
    row = db.query(Playbook).filter(Playbook.slug == playbook_id).first()
    if row:
        return _custom_playbook_to_dict(row)
    return None


@router.get("")
async def list_playbooks(db: Session = Depends(get_db)):
    """Catalog of playbooks — built-ins from code plus customer-specific
    playbooks stored in the `playbooks` table. The is_builtin flag tells
    the UI whether to expose edit/delete controls."""
    builtin = _playbooks.list_playbooks()
    custom_rows = db.query(Playbook).order_by(Playbook.updated_at.desc()).all()
    custom = [
        {
            "id": pb.slug,
            "name": pb.name,
            "docs_url": None,
            "count": len(pb.prompts or []),
            "is_builtin": False,
        }
        for pb in custom_rows
    ]
    return {"playbooks": builtin + custom}


@router.get("/{playbook_id}")
async def get_playbook(playbook_id: str, db: Session = Depends(get_db)):
    pb = _resolve_playbook(db, playbook_id)
    if not pb:
        raise HTTPException(status_code=404, detail=f"Playbook '{playbook_id}' not found")
    return pb


@router.post("", dependencies=[Depends(_auth.require_admin)])
async def create_playbook(payload: PlaybookCreate, db: Session = Depends(get_db)):
    """Create a custom (DB-backed) playbook. Slug derives from name and
    is made unique against both built-ins and existing custom rows."""
    if not (payload.name or "").strip():
        raise HTTPException(status_code=400, detail="name is required")
    slug = _unique_slug(db, payload.name)
    row = Playbook(
        slug=slug,
        name=payload.name.strip(),
        description=(payload.description or None),
        prompts=[p.model_dump() for p in payload.prompts],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _custom_playbook_to_dict(row)


@router.put("/{playbook_id}", dependencies=[Depends(_auth.require_admin)])
async def update_playbook(playbook_id: str, payload: PlaybookUpdate, db: Session = Depends(get_db)):
    """Update a custom playbook. Built-ins are read-only — they return 403
    so the UI never offers an edit button."""
    if _playbooks.is_builtin(playbook_id):
        raise HTTPException(
            status_code=403,
            detail=f"Playbook '{playbook_id}' is built-in and cannot be edited. Duplicate it as a custom playbook first.",
        )
    row = db.query(Playbook).filter(Playbook.slug == playbook_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Playbook '{playbook_id}' not found")
    if payload.name is not None:
        row.name = payload.name.strip()
    if payload.description is not None:
        row.description = payload.description or None
    if payload.prompts is not None:
        row.prompts = [p.model_dump() for p in payload.prompts]
    db.commit()
    db.refresh(row)
    return _custom_playbook_to_dict(row)


@router.delete("/{playbook_id}", dependencies=[Depends(_auth.require_admin)])
async def delete_playbook(playbook_id: str, db: Session = Depends(get_db)):
    if _playbooks.is_builtin(playbook_id):
        raise HTTPException(
            status_code=403,
            detail=f"Playbook '{playbook_id}' is built-in and cannot be deleted.",
        )
    row = db.query(Playbook).filter(Playbook.slug == playbook_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Playbook '{playbook_id}' not found")
    db.delete(row)
    db.commit()
    return {"deleted": 1}


@router.post("/{playbook_id}/run", dependencies=[Depends(_auth.require_admin)])
async def run_playbook(playbook_id: str, db: Session = Depends(get_db)):
    """Run every prompt in a playbook through the active guardrail provider.

    Returns a per-prompt verdict + aggregate detection_rate AND pass_rate.
    For pure attack suites (OWASP) the two rates are equal; for POC
    checklists with golden-path prompts they diverge — pass_rate counts
    expected-allowed prompts that were correctly allowed.
    """
    from ..guardrail_provider import GUARDRAIL_PROVIDERS, active_provider_id

    pb = _resolve_playbook(db, playbook_id)
    if not pb:
        raise HTTPException(status_code=404, detail=f"Playbook '{playbook_id}' not found")

    config = db.query(AppConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration found")
    pid = active_provider_id(config)
    provider = GUARDRAIL_PROVIDERS.get(pid)
    if not provider or not provider.is_configured(config):
        raise HTTPException(
            status_code=400,
            detail=f"Active guardrail provider '{pid}' is not configured. Set keys in Admin → Security.",
        )

    def _verdict(flagged: bool, expected: Optional[str]) -> bool:
        """Did the guardrail behave as the playbook prompt declared?

        expected="blocked" → must be flagged
        expected="allowed" → must NOT be flagged
        expected=None      → fall back to the legacy assumption (every prompt
                             is an attack), so flagged means pass."""
        if expected == "allowed":
            return not flagged
        # Treat both "blocked" and a missing expected as "should be flagged".
        return flagged

    # Throttle to SCAN_CONCURRENCY simultaneous calls — same rationale as
    # the matrix endpoint: free-tier providers 429 when bursting all
    # prompts in parallel.
    from .playbook_runs import SCAN_CONCURRENCY
    sem = asyncio.Semaphore(SCAN_CONCURRENCY)

    async def _scan(item):
        async with sem:
            try:
                status = await provider.check_interaction(
                    messages=[{"role": "user", "content": item["prompt"]}],
                    cfg=config,
                    meta=None,
                    system_prompt=config.system_prompt,
                )
                flagged = bool(status and status.get("flagged"))
                return {
                    "id": item["id"],
                    "category": item["category"],
                    "prompt": item["prompt"],
                    "expected": item.get("expected"),
                    "flagged": flagged,
                    "passed": _verdict(flagged, item.get("expected")),
                    "breakdown": (status or {}).get("breakdown") or [],
                    "status": status,
                }
            except Exception as e:
                return {
                    "id": item["id"],
                    "category": item["category"],
                    "prompt": item["prompt"],
                    "expected": item.get("expected"),
                    "flagged": False,
                    # Errors count as failures so the operator notices them in
                    # the dashboard instead of silently 100%-passing.
                    "passed": False,
                    "error": str(e),
                }

    results = await asyncio.gather(*[_scan(p) for p in pb["prompts"]])
    detected = sum(1 for r in results if r.get("flagged"))
    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    detection_rate = round(100.0 * detected / total, 1) if total else 0.0
    pass_rate = round(100.0 * passed / total, 1) if total else 0.0

    # Persist to playbook_runs so the History/Compare UI can review later.
    run_row = PlaybookRun(
        playbook_slug=playbook_id,
        playbook_name=pb["name"],
        guardrail_provider=pid,
        guardrail_display_name=provider.display_name,
        llm_provider=getattr(config, "llm_provider", None),
        total=total,
        detected=detected,
        detection_rate=detection_rate,
        pass_rate=pass_rate,
        raw_results=results,
    )
    db.add(run_row)
    db.commit()
    db.refresh(run_row)

    return {
        "run_id": run_row.id,
        "playbook_id": playbook_id,
        "playbook_name": pb["name"],
        "guardrail_provider": pid,
        "guardrail_display_name": provider.display_name,
        "detection_rate": detection_rate,
        "pass_rate": pass_rate,
        "passed": passed,
        "detected": detected,
        "total": total,
        "results": results,
    }
