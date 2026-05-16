"""Audit log writer.

Every chat call goes through `record_chat_turn()` to drop a row in the
`audit_log` table. The Admin Console exposes this as CSV/JSON via /api/audit
so customers can show their compliance/security team what the demo logs.
"""

import csv
import io
import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from . import audit_stream
from .models import AuditLog


def record_chat_turn(
    db: Session,
    *,
    user_message: str,
    assistant_response: Optional[str],
    conversation_id: Optional[int] = None,
    session_id: Optional[str] = None,
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
    guardrail_provider: Optional[str] = None,
    guardrail_status: Optional[Dict[str, Any]] = None,
    tool_traces: Optional[List[Dict[str, Any]]] = None,
    latency_ms: Optional[int] = None,
    blocked: bool = False,
    error: Optional[str] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: Optional[float] = None,
) -> Optional[int]:
    """Write one audit row. Returns the row id, or None on failure
    (never raises — audit writes must not break the chat flow)."""
    try:
        flagged = bool(guardrail_status and guardrail_status.get("flagged"))
        breakdown = (guardrail_status or {}).get("breakdown") if guardrail_status else None
        row = AuditLog(
            conversation_id=conversation_id,
            session_id=session_id,
            user_message=user_message or "",
            assistant_response=assistant_response or "",
            llm_provider=llm_provider,
            llm_model=llm_model,
            guardrail_provider=guardrail_provider,
            guardrail_flagged=flagged,
            guardrail_breakdown=breakdown,
            tool_traces=tool_traces or [],
            latency_ms=latency_ms,
            blocked=blocked,
            error=error,
            input_tokens=input_tokens or 0,
            output_tokens=output_tokens or 0,
            cost_usd=str(cost_usd) if cost_usd is not None else None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        try:
            audit_stream.publish(_row_to_dict(row))
        except Exception as pub_err:
            print(f"⚠️ audit_stream.publish failed: {pub_err}")
        return row.id
    except Exception as e:
        print(f"⚠️ audit.record_chat_turn failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return None


def list_entries(
    db: Session,
    *,
    limit: int = 200,
    offset: int = 0,
    flagged_only: bool = False,
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    q = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if flagged_only:
        q = q.filter(AuditLog.guardrail_flagged.is_(True))
    if session_id:
        q = q.filter(AuditLog.session_id == session_id)
    rows = q.offset(offset).limit(limit).all()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(r: AuditLog) -> Dict[str, Any]:
    return {
        "id": r.id,
        "conversation_id": r.conversation_id,
        "session_id": r.session_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "user_message": r.user_message,
        "assistant_response": r.assistant_response,
        "llm_provider": r.llm_provider,
        "llm_model": r.llm_model,
        "guardrail_provider": r.guardrail_provider,
        "guardrail_flagged": bool(r.guardrail_flagged),
        "guardrail_breakdown": r.guardrail_breakdown,
        "tool_traces": r.tool_traces,
        "latency_ms": r.latency_ms,
        "blocked": bool(r.blocked),
        "error": r.error,
        "input_tokens": r.input_tokens or 0,
        "output_tokens": r.output_tokens or 0,
        "cost_usd": float(r.cost_usd) if (r.cost_usd not in (None, "")) else None,
    }


def to_csv(entries: List[Dict[str, Any]]) -> str:
    """Flatten audit entries into a single CSV string."""
    if not entries:
        return ""
    fieldnames = [
        "id", "created_at", "session_id", "conversation_id",
        "llm_provider", "llm_model", "guardrail_provider",
        "guardrail_flagged", "blocked", "latency_ms",
        "input_tokens", "output_tokens", "cost_usd",
        "user_message", "assistant_response",
        "guardrail_breakdown", "tool_traces", "error",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for e in entries:
        row = dict(e)
        # Stringify JSON columns so Excel doesn't choke
        if isinstance(row.get("guardrail_breakdown"), (list, dict)):
            row["guardrail_breakdown"] = json.dumps(row["guardrail_breakdown"], ensure_ascii=False)
        if isinstance(row.get("tool_traces"), (list, dict)):
            row["tool_traces"] = json.dumps(row["tool_traces"], ensure_ascii=False)
        writer.writerow(row)
    return buf.getvalue()
