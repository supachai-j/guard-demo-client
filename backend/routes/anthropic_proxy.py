"""Anthropic-format gateway shim for clients locked to the `x-api-key` header.

Why this exists: some Anthropic-native clients (e.g. Claude for Office /
PowerPoint) hard-code their gateway auth as `x-api-key` and won't let you
change it. Portkey only accepts its key via `x-portkey-api-key` /
`Authorization: Bearer`, so pointing such a client straight at
`api.portkey.ai` returns `401 Invalid API Key (Error Code 03)`.

This endpoint sits in front of Portkey and bridges the two: the client points
its gateway URL at `https://<this-host>/v1` and keeps sending the Portkey API
key in `x-api-key`. We validate that key against the configured Portkey key
(so this is NOT an open relay — the caller must already hold the key), then
re-issue the request to Portkey with the correct `x-portkey-api-key` header
plus the active routing (`portkey_config` or `portkey_virtual_key`). Both
non-streaming and SSE streaming responses are proxied through unchanged.

The client only has to change one thing: its gateway URL. The locked
`x-api-key` header and the token value stay exactly as they were.
"""

import hmac
import logging
import os
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AppConfig

logger = logging.getLogger(__name__)

router = APIRouter(tags=["anthropic-proxy"])


def _proxy_enabled() -> bool:
    """Gate the relay behind an env flag (default on). Lets an operator who
    exposes this backend publicly turn the forward-with-server-credentials
    shim off without removing the route."""
    return (os.getenv("CLAUDE_OFFICE_PROXY_ENABLED", "1") or "1").strip().lower() not in {"0", "false", "off", "no"}

_DEFAULT_BASE = "https://api.portkey.ai/v1"
# Portkey sits behind Cloudflare, which 1010-blocks bare httpx/urllib UAs.
_UA = "Mozilla/5.0 (compatible; guard-demo-client)"
# Inbound headers worth forwarding to Portkey (auth + routing are set by us).
_FORWARD_HEADERS = ("anthropic-version", "anthropic-beta", "content-type")


def _anthropic_error(status: int, message: str) -> JSONResponse:
    """Return an error in the shape Anthropic clients expect."""
    return JSONResponse(
        status_code=status,
        content={"type": "error", "error": {"type": "authentication_error", "message": message}},
    )


def _portkey_base(cfg: AppConfig) -> str:
    custom = (getattr(cfg, "portkey_base_url", None) or "").strip()
    base = custom.rstrip("/") if custom else _DEFAULT_BASE
    return base if base.endswith("/v1") else f"{base}/v1"


def _routing_headers(cfg: AppConfig) -> Dict[str, str]:
    """Mirror the chat path's Portkey routing: config slug or virtual key."""
    headers: Dict[str, str] = {}
    config_id = (getattr(cfg, "portkey_config", None) or "").strip()
    virtual_key = (getattr(cfg, "portkey_virtual_key", None) or "").strip()
    if config_id:
        headers["x-portkey-config"] = config_id
    if virtual_key:
        headers["x-portkey-virtual-key"] = virtual_key
    return headers


def _authenticate(request: Request, cfg) -> Any:
    """Validate the client's x-api-key (or Bearer) against the Portkey key.

    Returns the Portkey key on success, or a JSONResponse error to short-circuit.
    """
    portkey_key = (getattr(cfg, "portkey_api_key", None) or "").strip() if cfg else ""
    if not portkey_key:
        return _anthropic_error(503, "Portkey is not configured on this gateway shim.")
    presented = (request.headers.get("x-api-key") or "").strip()
    if not presented:
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            presented = auth[7:].strip()
    if not presented or not hmac.compare_digest(presented, portkey_key):
        return _anthropic_error(401, "Invalid API key for this gateway.")
    return portkey_key


# Anthropic-style model list for the gateway connectivity / bootstrap probe.
# The active Portkey config overrides the model to whatever it targets
# (gemini today), so these ids are what the client offers in its picker.
_MODELS = [
    {"type": "model", "id": "claude-3-5-sonnet-20241022", "display_name": "Claude 3.5 Sonnet", "created_at": "2024-10-22T00:00:00Z"},
    {"type": "model", "id": "claude-3-5-haiku-20241022", "display_name": "Claude 3.5 Haiku", "created_at": "2024-10-22T00:00:00Z"},
    {"type": "model", "id": "claude-3-opus-20240229", "display_name": "Claude 3 Opus", "created_at": "2024-02-29T00:00:00Z"},
]


@router.get("/v1/models")
async def anthropic_models(request: Request, db: Session = Depends(get_db)):
    if not _proxy_enabled():
        return JSONResponse(status_code=404, content={"type": "error", "error": {"message": "Not found"}})
    auth = _authenticate(request, db.query(AppConfig).first())
    if isinstance(auth, JSONResponse):
        return auth
    return JSONResponse({
        "data": _MODELS,
        "has_more": False,
        "first_id": _MODELS[0]["id"],
        "last_id": _MODELS[-1]["id"],
    })


@router.post("/v1/messages")
async def anthropic_messages(request: Request, db: Session = Depends(get_db)):
    if not _proxy_enabled():
        # Hide the relay entirely when disabled.
        return JSONResponse(status_code=404, content={"type": "error", "error": {"message": "Not found"}})

    cfg = db.query(AppConfig).first()
    auth = _authenticate(request, cfg)
    if isinstance(auth, JSONResponse):
        return auth
    portkey_key = auth

    raw_body = await request.body()
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        payload = {}
    is_stream = bool(payload.get("stream"))

    out_headers = {
        "x-portkey-api-key": portkey_key,
        "User-Agent": _UA,
        "content-type": "application/json",
    }
    out_headers.update(_routing_headers(cfg))
    for h in _FORWARD_HEADERS:
        v = request.headers.get(h)
        if v and h not in out_headers:
            out_headers[h] = v

    url = f"{_portkey_base(cfg)}/messages"

    if not is_stream:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(url, headers=out_headers, content=raw_body)
        except Exception as e:  # noqa: BLE001
            logger.warning("Anthropic proxy transport error: %s", e)
            return _anthropic_error(502, f"Upstream gateway error: {e}")
        # Pass the upstream Anthropic-shaped body + status straight through.
        return JSONResponse(status_code=resp.status_code, content=_safe_json(resp))

    async def _proxy_stream():
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", url, headers=out_headers, content=raw_body) as upstream:
                    async for chunk in upstream.aiter_raw():
                        if chunk:
                            yield chunk
        except Exception as e:  # noqa: BLE001
            logger.warning("Anthropic proxy stream error: %s", e)
            yield b"event: error\ndata: {\"type\":\"error\",\"error\":{\"message\":\"upstream stream error\"}}\n\n"

    return StreamingResponse(_proxy_stream(), media_type="text/event-stream")


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"type": "error", "error": {"message": resp.text[:500]}}
