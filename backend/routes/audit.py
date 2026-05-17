"""Audit log endpoints + cost summary + PDF report + live SSE stream.

`/api/audit/stream` is the live attack feed: the browser EventSource
API can't set Authorization headers, so it authenticates via `?token=`
query param (validated against the JWT secret manually)."""

import asyncio
import io
import json
from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import audit, audit_stream
from .. import auth as _auth
from ..database import get_db
from ..models import AuditLog

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", dependencies=[Depends(_auth.require_admin)])
async def get_audit_log(
    format: str = "json",
    limit: int = 200,
    offset: int = 0,
    flagged_only: bool = False,
    session_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Return audit_log rows. format=csv returns text/csv attachment."""
    entries = audit.list_entries(
        db,
        limit=min(max(limit, 1), 1000),
        offset=max(offset, 0),
        flagged_only=flagged_only,
        session_id=session_id,
    )
    if format == "csv":
        csv_text = audit.to_csv(entries)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return StreamingResponse(
            io.BytesIO(csv_text.encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=audit_{timestamp}.csv"},
        )
    return {"entries": entries, "count": len(entries)}


@router.delete("", dependencies=[Depends(_auth.require_admin)])
async def clear_audit_log(db: Session = Depends(get_db)):
    """Wipe audit_log entries (admin / demo-reset only)."""
    deleted = db.query(AuditLog).delete()
    db.commit()
    return {"deleted": deleted}


@router.get("/cost-summary", dependencies=[Depends(_auth.require_admin)])
async def audit_cost_summary(db: Session = Depends(get_db)):
    """Aggregate audit_log into per-provider cost/tokens for the Cost panel."""
    rows = audit.list_entries(db, limit=1000)
    by_provider: Dict[str, Dict[str, float]] = {}
    total_cost = 0.0
    total_in = 0
    total_out = 0
    for r in rows:
        prov = r.get("llm_provider") or "—"
        bucket = by_provider.setdefault(prov, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        bucket["calls"] += 1
        bucket["input_tokens"] += r.get("input_tokens") or 0
        bucket["output_tokens"] += r.get("output_tokens") or 0
        cost = r.get("cost_usd") or 0.0
        bucket["cost_usd"] += cost
        total_cost += cost
        total_in += r.get("input_tokens") or 0
        total_out += r.get("output_tokens") or 0
    return {
        "total_cost_usd": round(total_cost, 6),
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "by_provider": [
            {"provider": k, **{kk: (round(vv, 6) if isinstance(vv, float) else vv) for kk, vv in v.items()}}
            for k, v in by_provider.items()
        ],
    }


@router.get("/report.pdf", dependencies=[Depends(_auth.require_admin)])
async def audit_report_pdf(limit: int = 200, db: Session = Depends(get_db)):
    """Render the last N audit entries as a 1-2 page PDF summary."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    entries = audit.list_entries(db, limit=min(max(limit, 1), 500))
    total = len(entries)
    flagged = sum(1 for e in entries if e.get("guardrail_flagged"))
    blocked = sum(1 for e in entries if e.get("blocked"))
    total_cost = sum((e.get("cost_usd") or 0.0) for e in entries)
    by_provider: Dict[str, int] = {}
    for e in entries:
        by_provider[e.get("guardrail_provider") or "—"] = by_provider.get(e.get("guardrail_provider") or "—", 0) + 1

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                             topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Title"], spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], spaceBefore=12, spaceAfter=4)
    body = styles["BodyText"]

    story = []
    story.append(Paragraph("guard-demo-client — Audit Summary", title_style))
    story.append(Paragraph(f"Generated {datetime.utcnow().isoformat(timespec='seconds')}Z · last {total} entries", body))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Summary", h2))
    summary_data = [
        ["Total entries", str(total)],
        ["Flagged by guardrail", f"{flagged} ({100*flagged/total:.0f}%)" if total else "0"],
        ["Blocked (blocking mode)", str(blocked)],
        ["Total estimated cost (USD)", f"${total_cost:.4f}"],
    ]
    summary_tbl = Table(summary_data, colWidths=[6 * cm, 8 * cm])
    summary_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(summary_tbl)

    story.append(Paragraph("Entries by guardrail provider", h2))
    rows = [["Provider", "Count"]] + [[k, str(v)] for k, v in by_provider.items()]
    prov_tbl = Table(rows, colWidths=[10 * cm, 4 * cm])
    prov_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(prov_tbl)

    story.append(Paragraph("Latest flagged events (max 20)", h2))
    flagged_entries = [e for e in entries if e.get("guardrail_flagged")][:20]
    if flagged_entries:
        head = ["When", "Provider", "Prompt (truncated)"]
        rows = [head]
        for e in flagged_entries:
            when = (e.get("created_at") or "")[:19].replace("T", " ")
            prompt_ = (e.get("user_message") or "")[:80]
            rows.append([when, e.get("guardrail_provider") or "", prompt_])
        flag_tbl = Table(rows, colWidths=[4 * cm, 3 * cm, 10 * cm])
        flag_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fef2f2")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#fecaca")),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("PADDING", (0, 0), (-1, -1), 3),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(flag_tbl)
    else:
        story.append(Paragraph("No flagged events in this window.", body))

    doc.build(story)
    buf.seek(0)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        io.BytesIO(buf.getvalue()),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=audit_report_{timestamp}.pdf"},
    )


@router.get("/stream")
async def audit_stream_endpoint(
    token: Optional[str] = Query(None, description="JWT (EventSource can't set headers)"),
    flagged_only: bool = Query(True, description="Default: only flagged events. Set false for all turns."),
):
    """Server-Sent Events feed of audit rows as they're written.

    The browser EventSource API can't attach an Authorization header, so we
    accept the JWT as a `?token=` query parameter and validate it manually.
    """
    _auth.verify_token(token)
    q = audit_stream.subscribe()

    async def gen():
        try:
            # Initial handshake so the client knows it's connected.
            yield f"event: hello\ndata: {json.dumps({'subscribers': audit_stream.subscriber_count()})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Keep-alive comment so proxies don't reap idle connections.
                    yield ": keep-alive\n\n"
                    continue
                if flagged_only and not event.get("guardrail_flagged"):
                    continue
                yield f"event: audit\ndata: {json.dumps(event)}\n\n"
        finally:
            audit_stream.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
