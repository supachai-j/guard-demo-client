"""Playbook run history endpoints — list, detail, compare, delete.

Each `POST /api/playbooks/{id}/run` persists a `PlaybookRun` row.
This router exposes read/compare views so the UI can show history
across runs and side-by-side compare across guardrail providers.
"""

import asyncio
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import auth as _auth
from .. import playbooks as _builtin_playbooks
from ..database import get_db
from ..models import AppConfig, Playbook, PlaybookRun

router = APIRouter(prefix="/api/playbook-runs", tags=["playbook-runs"])

# Concurrent calls per provider. Most managed guardrail providers throttle
# free-tier accounts at ~60 req/min — bursting all 26 prompts in parallel
# triggers 429s + silent null breakdowns. Cap at 5 simultaneous so a 26-prompt
# playbook spreads over ~5 batches (~1-2s total at typical 200-400ms latency).
SCAN_CONCURRENCY = 5


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


class MultiProviderRunRequest(BaseModel):
    playbook_id: str
    provider_ids: List[str]


class MatrixRunRequest(BaseModel):
    playbook_ids: List[str]
    provider_ids: List[str]


@router.post("/multi-provider", dependencies=[Depends(_auth.require_admin)])
async def run_multi_provider(payload: MultiProviderRunRequest, db: Session = Depends(get_db)):
    """Fan a playbook across N selected guardrail providers in one call.

    Saves one PlaybookRun row per provider (so they appear in Run History) and
    returns the same shape as `/compare` (runs + per-prompt matrix) so the UI
    can render comparison immediately without a second roundtrip.

    Active provider config is NOT changed — we resolve each provider from
    GUARDRAIL_PROVIDERS and call `check_interaction(cfg=config)` directly,
    same pattern as `/api/chat/compare-guardrails`.
    """
    from ..guardrail_provider import GUARDRAIL_PROVIDERS

    if not payload.provider_ids:
        raise HTTPException(status_code=400, detail="provider_ids must be non-empty")
    if len(payload.provider_ids) > 6:
        raise HTTPException(status_code=400, detail="max 6 providers per fan-out")

    config = db.query(AppConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration found")

    # Resolve playbook (built-in or custom)
    pb_dict = None
    if _builtin_playbooks.is_builtin(payload.playbook_id):
        pb_dict = _builtin_playbooks.get_playbook(payload.playbook_id)
    else:
        row = db.query(Playbook).filter(Playbook.slug == payload.playbook_id).first()
        if row:
            pb_dict = {
                "id": row.slug,
                "name": row.name,
                "description": row.description,
                "prompts": row.prompts or [],
            }
    if not pb_dict:
        raise HTTPException(status_code=404, detail=f"Playbook '{payload.playbook_id}' not found")

    def _verdict(flagged: bool, expected: Optional[str]) -> bool:
        if expected == "allowed":
            return not flagged
        return flagged

    async def _scan_one(provider, item):
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
                "category": item.get("category"),
                "prompt": item["prompt"],
                "expected": item.get("expected"),
                "flagged": flagged,
                "passed": _verdict(flagged, item.get("expected")),
                "breakdown": (status or {}).get("breakdown") or [],
            }
        except Exception as e:
            return {
                "id": item["id"],
                "category": item.get("category"),
                "prompt": item["prompt"],
                "expected": item.get("expected"),
                "flagged": False,
                "passed": False,
                "error": str(e),
            }

    async def _run_provider(pid: str):
        provider = GUARDRAIL_PROVIDERS.get(pid)
        if not provider:
            return None, {"error": f"unknown provider '{pid}'"}
        if not provider.is_configured(config):
            return None, {"error": f"provider '{pid}' not configured"}
        results = await asyncio.gather(*[_scan_one(provider, p) for p in pb_dict["prompts"]])
        detected = sum(1 for r in results if r.get("flagged"))
        passed = sum(1 for r in results if r.get("passed"))
        total = len(results)
        row = PlaybookRun(
            playbook_slug=payload.playbook_id,
            playbook_name=pb_dict["name"],
            guardrail_provider=pid,
            guardrail_display_name=provider.display_name,
            llm_provider=getattr(config, "llm_provider", None),
            total=total,
            detected=detected,
            detection_rate=round(100.0 * detected / total, 1) if total else 0.0,
            pass_rate=round(100.0 * passed / total, 1) if total else 0.0,
            raw_results=results,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row, None

    # Run providers sequentially to avoid DB write race; per-prompt is still
    # parallel within each provider.
    created_rows: List[PlaybookRun] = []
    errors: List[dict] = []
    for pid in payload.provider_ids:
        row, err = await _run_provider(pid)
        if row:
            created_rows.append(row)
        elif err:
            errors.append({"provider": pid, **err})

    # Build per-prompt matrix (same shape as /compare endpoint)
    prompts_index: dict = {}
    for run in created_rows:
        for r in (run.raw_results or []):
            pid_key = r.get("id")
            if pid_key is None:
                continue
            if pid_key not in prompts_index:
                prompts_index[pid_key] = {
                    "id": pid_key,
                    "category": r.get("category"),
                    "prompt": r.get("prompt"),
                    "expected": r.get("expected"),
                    "by_run": {},
                }
            # Use string key explicitly so JSON consumers see consistent
            # string-typed keys (Python int dict keys serialize to JSON
            # strings anyway, but explicit is safer for typed clients).
            prompts_index[pid_key]["by_run"][str(run.id)] = {
                "flagged": r.get("flagged"),
                "passed": r.get("passed"),
                "error": r.get("error"),
            }

    return {
        "playbook_id": payload.playbook_id,
        "playbook_name": pb_dict["name"],
        "runs": [_summary(r) for r in created_rows],
        "prompts": list(prompts_index.values()),
        "errors": errors,
    }


async def _run_playbook_against_providers(
    playbook_id: str, provider_ids: List[str], db: Session
) -> dict:
    """Shared helper: run one playbook against N providers, return same shape
    as /multi-provider. Used by /multi-provider and /matrix endpoints."""
    from ..guardrail_provider import GUARDRAIL_PROVIDERS

    config = db.query(AppConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration found")

    pb_dict = None
    if _builtin_playbooks.is_builtin(playbook_id):
        pb_dict = _builtin_playbooks.get_playbook(playbook_id)
    else:
        row = db.query(Playbook).filter(Playbook.slug == playbook_id).first()
        if row:
            pb_dict = {
                "id": row.slug,
                "name": row.name,
                "description": row.description,
                "prompts": row.prompts or [],
            }
    if not pb_dict:
        return {"playbook_id": playbook_id, "error": f"playbook '{playbook_id}' not found", "runs": [], "prompts": []}

    def _verdict(flagged: bool, expected: Optional[str]) -> bool:
        if expected == "allowed":
            return not flagged
        return flagged

    async def _scan_one(provider, item, sem: asyncio.Semaphore):
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
                    "id": item["id"], "category": item.get("category"), "prompt": item["prompt"],
                    "expected": item.get("expected"), "flagged": flagged,
                    "passed": _verdict(flagged, item.get("expected")),
                    "breakdown": (status or {}).get("breakdown") or [],
                    # Mark provider returning None (likely rate limit or
                    # upstream failure that the provider swallowed) so the
                    # aggregate can warn instead of silently scoring 0%.
                    "null_status": status is None,
                }
            except Exception as e:
                return {
                    "id": item["id"], "category": item.get("category"), "prompt": item["prompt"],
                    "expected": item.get("expected"), "flagged": False, "passed": False, "error": str(e),
                }

    created_rows: List[PlaybookRun] = []
    errors: List[dict] = []
    for pid in provider_ids:
        provider = GUARDRAIL_PROVIDERS.get(pid)
        if not provider:
            errors.append({"provider": pid, "error": f"unknown provider '{pid}'"})
            continue
        if not provider.is_configured(config):
            errors.append({"provider": pid, "error": f"provider '{pid}' not configured"})
            continue
        # Throttle per-provider: SCAN_CONCURRENCY simultaneous calls max.
        # Fresh semaphore per provider so providers don't starve each other.
        sem = asyncio.Semaphore(SCAN_CONCURRENCY)
        results = await asyncio.gather(*[_scan_one(provider, p, sem) for p in pb_dict["prompts"]])
        # Surface "many null statuses" as a provider-level warning so the
        # caller doesn't mistake a silent rate-limit for a clean 0% pass.
        null_count = sum(1 for r in results if r.get("null_status"))
        error_count = sum(1 for r in results if r.get("error"))
        if null_count >= max(1, len(results) // 2) or error_count >= max(1, len(results) // 2):
            errors.append({
                "provider": pid,
                "error": f"{null_count} null + {error_count} error out of {len(results)} prompts — likely rate-limited or upstream outage",
            })
        detected = sum(1 for r in results if r.get("flagged"))
        passed = sum(1 for r in results if r.get("passed"))
        total = len(results)
        row = PlaybookRun(
            playbook_slug=playbook_id,
            playbook_name=pb_dict["name"],
            guardrail_provider=pid,
            guardrail_display_name=provider.display_name,
            llm_provider=getattr(config, "llm_provider", None),
            total=total, detected=detected,
            detection_rate=round(100.0 * detected / total, 1) if total else 0.0,
            pass_rate=round(100.0 * passed / total, 1) if total else 0.0,
            raw_results=results,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        created_rows.append(row)

    # Per-prompt matrix for this playbook
    prompts_index: dict = {}
    for run in created_rows:
        for r in (run.raw_results or []):
            pid_key = r.get("id")
            if pid_key is None:
                continue
            if pid_key not in prompts_index:
                prompts_index[pid_key] = {
                    "id": pid_key, "category": r.get("category"),
                    "prompt": r.get("prompt"), "expected": r.get("expected"),
                    "by_run": {},
                }
            prompts_index[pid_key]["by_run"][str(run.id)] = {
                "flagged": r.get("flagged"), "passed": r.get("passed"), "error": r.get("error"),
            }

    return {
        "playbook_id": playbook_id,
        "playbook_name": pb_dict["name"],
        "runs": [_summary(r) for r in created_rows],
        "prompts": list(prompts_index.values()),
        "errors": errors,
    }


@router.post("/matrix", dependencies=[Depends(_auth.require_admin)])
async def run_matrix(payload: MatrixRunRequest, db: Session = Depends(get_db)):
    """Fan M playbooks × N providers — creates one PlaybookRun row per
    (playbook, provider) cell. Returns `{playbooks: [...]}` where each
    element is the same shape as /multi-provider response."""
    if not payload.playbook_ids:
        raise HTTPException(status_code=400, detail="playbook_ids must be non-empty")
    if not payload.provider_ids:
        raise HTTPException(status_code=400, detail="provider_ids must be non-empty")
    if len(payload.playbook_ids) > 10:
        raise HTTPException(status_code=400, detail="max 10 playbooks per matrix")
    if len(payload.provider_ids) > 6:
        raise HTTPException(status_code=400, detail="max 6 providers per matrix")

    out = []
    for pb_id in payload.playbook_ids:
        out.append(await _run_playbook_against_providers(pb_id, payload.provider_ids, db))
    return {"playbooks": out}


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
