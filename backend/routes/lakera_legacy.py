"""Legacy Lakera overlay polling endpoints.

Kept for the public landing page's "live Lakera status" panel — the chat
widget polls /api/lakera/last to populate the overlay. New code should use
the unified guardrail status from the chat response instead."""

from fastapi import APIRouter, HTTPException

from .. import lakera

router = APIRouter(prefix="/api/lakera", tags=["lakera-legacy"])


@router.get("/last")
async def get_last_lakera_result():
    """Get the last Lakera result for frontend polling"""
    result = lakera.get_last_result()
    if result is None:
        raise HTTPException(status_code=404, detail="No Lakera result available")
    return result


@router.get("/last_request")
async def get_last_lakera_request():
    """Get the last Lakera request payload for debugging (messages + metadata)"""
    req = lakera.get_last_request()
    if req is None:
        raise HTTPException(status_code=404, detail="No Lakera request recorded yet")
    return req
