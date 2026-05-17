"""Playbook run history endpoints — list, detail, compare, delete.

Each `POST /api/playbooks/{id}/run` persists a `PlaybookRun` row.
This router exposes read/compare views so the UI can show history
across runs and side-by-side compare across guardrail providers.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import auth as _auth
from ..database import get_db
from ..models import PlaybookRun

router = APIRouter(prefix="/api/playbook-runs", tags=["playbook-runs"])


def _summary(row: PlaybookRun) -> dict:
    return {
        "id": row.id,
        "playbook_slug": row.playbook_slug,
        "playbook_name": row.playbook_name,
        "guardrail_provider": row.guardrail_provider,
        "guardrail_display_name": row.guardrail_display_name,
        "llm_provider": row.llm_provider,
        "total": row.total,
        "detected": row.detected,
        "detection_rate": row.detection_rate,
        "pass_rate": row.pass_rate,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("", dependencies=[Depends(_auth.require_admin)])
async def list_runs(
    db: Session = Depends(get_db),
    playbook_slug: Optional[str] = Query(None),
    guardrail_provider: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    q = db.query(PlaybookRun)
    if playbook_slug:
        q = q.filter(PlaybookRun.playbook_slug == playbook_slug)
    if guardrail_provider:
        q = q.filter(PlaybookRun.guardrail_provider == guardrail_provider)
    rows = q.order_by(PlaybookRun.created_at.desc()).limit(limit).all()
    return {"runs": [_summary(r) for r in rows], "count": len(rows)}


@router.get("/compare", dependencies=[Depends(_auth.require_admin)])
async def compare_runs(
    db: Session = Depends(get_db),
    ids: str = Query(..., description="Comma-separated run IDs, e.g. '1,2,3'"),
):
    """Side-by-side comparison of 2-5 runs.

    Returns aggregate metrics per run + per-prompt verdicts indexed by prompt
    id so the UI can render rows where columns are runs and cells are pass/fail.
    """
    try:
        id_list = [int(x.strip()) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids must be comma-separated integers")
    if not (2 <= len(id_list) <= 5):
        raise HTTPException(status_code=400, detail="compare 2-5 runs at a time")

    rows = db.query(PlaybookRun).filter(PlaybookRun.id.in_(id_list)).all()
    if len(rows) != len(id_list):
        found = {r.id for r in rows}
        missing = [i for i in id_list if i not in found]
        raise HTTPException(status_code=404, detail=f"runs not found: {missing}")

    # Preserve user-supplied order
    by_id = {r.id: r for r in rows}
    ordered = [by_id[i] for i in id_list]

    # Per-prompt matrix: { prompt_id: { run_id: {flagged, passed, category, prompt} } }
    prompts_index: dict = {}
    for run in ordered:
        for r in (run.raw_results or []):
            pid = r.get("id")
            if pid is None:
                continue
            if pid not in prompts_index:
                prompts_index[pid] = {
                    "id": pid,
                    "category": r.get("category"),
                    "prompt": r.get("prompt"),
                    "expected": r.get("expected"),
                    "by_run": {},
                }
            prompts_index[pid]["by_run"][run.id] = {
                "flagged": r.get("flagged"),
                "passed": r.get("passed"),
                "error": r.get("error"),
            }

    return {
        "runs": [_summary(r) for r in ordered],
        "prompts": list(prompts_index.values()),
    }


@router.get("/{run_id}", dependencies=[Depends(_auth.require_admin)])
async def get_run(run_id: int, db: Session = Depends(get_db)):
    row = db.query(PlaybookRun).filter(PlaybookRun.id == run_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    return {**_summary(row), "results": row.raw_results or []}


@router.patch("/{run_id}", dependencies=[Depends(_auth.require_admin)])
async def update_run_notes(run_id: int, payload: dict, db: Session = Depends(get_db)):
    """Update the user-editable notes field. The run's measurements are
    immutable — only `notes` can change."""
    row = db.query(PlaybookRun).filter(PlaybookRun.id == run_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    if "notes" in payload:
        row.notes = payload["notes"] or None
        db.commit()
        db.refresh(row)
    return _summary(row)


@router.delete("/{run_id}", dependencies=[Depends(_auth.require_admin)])
async def delete_run(run_id: int, db: Session = Depends(get_db)):
    row = db.query(PlaybookRun).filter(PlaybookRun.id == run_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    db.delete(row)
    db.commit()
    return {"deleted": 1, "id": run_id}
