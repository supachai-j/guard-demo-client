"""Session recorder — capture a sequence of chat prompts and replay them
through the current agent stack. Used by demo operators to show
deterministic flows even when the underlying LLM is non-deterministic."""

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import auth as _auth
from .. import llm_client
from ..agent import AgentRequest, run_agent
from ..database import get_db
from ..models import AppConfig, SessionRecording

router = APIRouter(prefix="/api/recordings", tags=["recordings"], dependencies=[Depends(_auth.require_admin)])


@router.get("")
async def list_recordings(db: Session = Depends(get_db)):
    rows = db.query(SessionRecording).order_by(SessionRecording.created_at.desc()).all()
    return {
        "recordings": [
            {
                "id": r.id,
                "name": r.name,
                "notes": r.notes,
                "event_count": len(r.events or []),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.post("")
async def create_recording(payload: dict, db: Session = Depends(get_db)):
    """Save a captured session. Body: { name, notes?, events: [{ts,prompt,response,...}] }"""
    name = (payload or {}).get("name") or f"Recording {datetime.utcnow().isoformat(timespec='seconds')}"
    events = (payload or {}).get("events") or []
    if not isinstance(events, list):
        raise HTTPException(status_code=400, detail="events must be a list")
    rec = SessionRecording(
        name=name[:200],
        notes=(payload or {}).get("notes"),
        events=events,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"id": rec.id, "name": rec.name, "event_count": len(events)}


@router.get("/{recording_id}")
async def get_recording(recording_id: int, db: Session = Depends(get_db)):
    rec = db.query(SessionRecording).filter(SessionRecording.id == recording_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    return {
        "id": rec.id,
        "name": rec.name,
        "notes": rec.notes,
        "events": rec.events or [],
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


@router.delete("/{recording_id}")
async def delete_recording(recording_id: int, db: Session = Depends(get_db)):
    rec = db.query(SessionRecording).filter(SessionRecording.id == recording_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    db.delete(rec)
    db.commit()
    return {"deleted": recording_id}


@router.post("/{recording_id}/replay")
async def replay_recording(recording_id: int, db: Session = Depends(get_db)):
    """Re-run every captured prompt through the current agent stack.

    Each event in the recording must have a `prompt` field; the response is
    captured along with the guardrail verdict so the caller can diff against
    the original recording.
    """
    rec = db.query(SessionRecording).filter(SessionRecording.id == recording_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    config = db.query(AppConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration found")
    llm_client.ensure_active_model_valid(config, db)

    results: List[dict] = []
    for event in rec.events or []:
        prompt = (event or {}).get("prompt") if isinstance(event, dict) else None
        if not prompt:
            continue
        req = AgentRequest(message=prompt, session_id=f"replay-{recording_id}")
        result = await run_agent(req, config, db, persist=False)
        results.append(
            {
                "prompt": prompt,
                "original": event.get("response") if isinstance(event, dict) else None,
                "replay_response": result.response,
                "lakera": result.lakera_status,
                "tool_traces": result.tool_traces,
                "citations": result.citations,
            }
        )
    return {"recording_id": recording_id, "name": rec.name, "results": results}
