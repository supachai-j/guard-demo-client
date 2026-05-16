"""Outbound webhooks fired on flagged guardrail events.

The admin configures a single `webhook_url`. When a guardrail flags content,
we POST a JSON payload to that URL (fire-and-forget — never blocks the chat
flow). Payload shape:

    {
      "type": "guardrail.flagged",
      "ts": "2026-05-16T10:30:00Z",
      "session_id": "...",
      "conversation_id": 42,
      "user_message": "...",
      "assistant_response": "...",
      "guardrail_provider": "lakera",
      "flagged": true,
      "breakdown": [...]
    }

Customers wire this into Slack, PagerDuty, SOAR pipelines, etc.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


async def _post_with_timeout(url: str, payload: Dict[str, Any], timeout: float = 5.0) -> None:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                logger.warning("webhook %s returned %s: %s", url, resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("webhook %s failed: %s", url, e)


async def fire_flagged_event(
    cfg: Any,
    *,
    user_message: str,
    assistant_response: Optional[str],
    guardrail_status: Dict[str, Any],
    session_id: Optional[str] = None,
    conversation_id: Optional[int] = None,
) -> None:
    """Fire-and-forget POST to the configured webhook URL. Never raises."""
    url = (getattr(cfg, "webhook_url", None) or "").strip()
    if not url:
        return

    payload = {
        "type": "guardrail.flagged",
        "ts": datetime.utcnow().isoformat() + "Z",
        "session_id": session_id,
        "conversation_id": conversation_id,
        "user_message": user_message,
        "assistant_response": assistant_response,
        "guardrail_provider": (guardrail_status or {}).get("metadata", {}).get("source"),
        "flagged": bool((guardrail_status or {}).get("flagged")),
        "breakdown": (guardrail_status or {}).get("breakdown") or [],
    }
    # Schedule without awaiting result to keep chat path fast.
    try:
        asyncio.create_task(_post_with_timeout(url, payload))
    except RuntimeError:
        # No running loop (e.g. sync test): just do it inline best-effort.
        try:
            asyncio.run(_post_with_timeout(url, payload))
        except Exception:
            pass


async def fire_test_event(url: str) -> Dict[str, Any]:
    """Used by the Admin UI 'Test webhook' button. Returns status info."""
    payload = {
        "type": "guardrail.test",
        "ts": datetime.utcnow().isoformat() + "Z",
        "message": "Test webhook from guard-demo-client Admin Console.",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return {"ok": resp.status_code < 400, "status": resp.status_code, "body": resp.text[:500]}
    except Exception as e:
        return {"ok": False, "status": 0, "error": str(e)}
