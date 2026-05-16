"""In-process pub/sub for live audit events.

Subscribers (SSE handlers) call `subscribe()` to receive an `asyncio.Queue`
and `unsubscribe()` when the connection closes. The audit writer
(`audit.record_chat_turn`) calls `publish()` after every successful insert.

Publish is non-blocking: if a subscriber's queue is full (slow consumer),
the event is dropped for that subscriber rather than back-pressuring the
chat path. Audit writes must never slow down or break user requests.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Set

logger = logging.getLogger(__name__)

_MAX_QUEUE_PER_SUB = 100
_subscribers: Set[asyncio.Queue] = set()


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE_PER_SUB)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def publish(event: Dict[str, Any]) -> None:
    """Fan event to every subscriber. Never raises; drops on slow consumers."""
    if not _subscribers:
        return
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug("audit_stream subscriber queue full; dropping event")
        except Exception as e:
            logger.debug("audit_stream publish failed for one subscriber: %s", e)


def subscriber_count() -> int:
    return len(_subscribers)
