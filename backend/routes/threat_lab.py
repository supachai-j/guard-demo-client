"""Threat Lab miscellanea — endpoints that don't belong to a single
domain (audit / playbook / recordings) but power Threat Lab panels:

  /api/webhook/test          — fire a test event to the saved webhook URL
  /api/batch/run             — bulk-eval a CSV of prompts through the active guardrail
  /api/health/providers      — ping every configured LLM + guardrail (latency)
  /api/chat/compare-llms     — fan one prompt to N LLM providers in parallel
  /api/chat/compare-guardrails — same prompt → every configured guardrail
  /api/moderation/image      — image scan via the active guardrail
"""

import asyncio
import csv
import io as _io
import time as _t
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import auth as _auth
from .. import costs as cost_module
from .. import llm_client, webhooks
from .._config_override import ConfigOverride as _ConfigOverride
from ..database import get_db
from ..models import AppConfig
from ..schemas import ChatRequest

router = APIRouter(tags=["threat-lab"])


@router.post("/api/webhook/test", dependencies=[Depends(_auth.require_admin)])
async def test_webhook(payload: dict, db: Session = Depends(get_db)):
    """Send a synthetic 'guardrail.test' event to the saved webhook_url so the
    admin can verify the integration before relying on it."""
    config = db.query(AppConfig).first()
    url = (payload or {}).get("url") or (config and config.webhook_url) or ""
    if not url.strip():
        raise HTTPException(status_code=400, detail="webhook_url is empty")
    result = await webhooks.fire_test_event(url.strip())
    return result


@router.post("/api/batch/run", dependencies=[Depends(_auth.require_admin)])
async def batch_run(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a CSV with a 'prompt' column (or one prompt per line if no
    header). For each prompt, run the active guardrail and return verdict +
    breakdown. Skips the LLM call — guardrail-only eval, optimised for speed
    on 100+ prompts."""
    from ..guardrail_provider import GUARDRAIL_PROVIDERS, active_provider_id

    config = db.query(AppConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration found")
    pid = active_provider_id(config)
    provider = GUARDRAIL_PROVIDERS.get(pid)
    if not provider or not provider.is_configured(config):
        raise HTTPException(
            status_code=400,
            detail=f"Active guardrail provider '{pid}' is not configured.",
        )

    content = (await file.read()).decode("utf-8", errors="replace")
    if not content.strip():
        raise HTTPException(status_code=400, detail="empty file")

    # Try CSV with header first; fall back to one-prompt-per-line.
    prompts: List[str] = []
    sniff = content[:512]
    if "," in sniff or '"' in sniff:
        try:
            reader = csv.DictReader(_io.StringIO(content))
            field = None
            for cand in ("prompt", "Prompt", "text", "Text", "message"):
                if reader.fieldnames and cand in reader.fieldnames:
                    field = cand
                    break
            if field:
                prompts = [(row.get(field) or "").strip() for row in reader if (row.get(field) or "").strip()]
        except Exception:
            prompts = []
    if not prompts:
        prompts = [ln.strip() for ln in content.splitlines() if ln.strip() and not ln.startswith("#")]

    if not prompts:
        raise HTTPException(status_code=400, detail="no prompts found in file")
    if len(prompts) > 500:
        raise HTTPException(status_code=400, detail="too many prompts (max 500 per batch)")

    results: List[Dict[str, Any]] = []
    for prompt_text in prompts:
        try:
            status = await provider.check_interaction(
                messages=[{"role": "user", "content": prompt_text}],
                cfg=config,
                meta=None,
                system_prompt=config.system_prompt,
            )
            results.append({
                "prompt": prompt_text,
                "flagged": bool(status and status.get("flagged")),
                "breakdown": (status or {}).get("breakdown") or [],
            })
        except Exception as e:
            results.append({"prompt": prompt_text, "flagged": False, "error": str(e)})

    detected = sum(1 for r in results if r.get("flagged"))
    return {
        "guardrail_provider": pid,
        "guardrail_display_name": provider.display_name,
        "total": len(results),
        "detected": detected,
        "detection_rate": round(100.0 * detected / len(results), 1) if results else 0.0,
        "results": results,
    }


@router.get("/api/health/providers", dependencies=[Depends(_auth.require_admin)])
async def health_providers(db: Session = Depends(get_db)):
    """For each configured LLM provider, send a 1-token "ping" request; for
    each configured guardrail, run a benign 1-word check. Returns up/down +
    latency per provider so the Admin Console can show a status panel.
    """
    from ..guardrail_provider import GUARDRAIL_PROVIDERS
    from ..providers import PROVIDERS, provider_api_key

    config = db.query(AppConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration found")

    async def _llm_check(pid: str):
        meta = PROVIDERS.get(pid, {})
        # Configured = either has API key or doesn't need one (Ollama, etc.)
        has_key = bool(provider_api_key(_ConfigOverride(config, llm_provider=pid)))
        if meta.get("needs_key") and not has_key:
            return {"id": pid, "display_name": meta.get("display_name"), "kind": "llm",
                    "configured": False, "ok": False, "latency_ms": 0, "error": None}
        t0 = _t.monotonic()
        try:
            # Use the first static model as a smoke test target.
            models = meta.get("models") or []
            model = models[0] if models else config.openai_model
            override = _ConfigOverride(config, llm_provider=pid, openai_model=model)
            resp = llm_client.chat_completion(
                messages=[{"role": "user", "content": "ping"}],
                model=model,
                temperature=0,
                config=override,
            )
            ok = bool((resp or {}).get("choices"))
            return {"id": pid, "display_name": meta.get("display_name"), "kind": "llm",
                    "configured": True, "ok": ok, "latency_ms": int((_t.monotonic() - t0) * 1000),
                    "error": None}
        except Exception as e:
            return {"id": pid, "display_name": meta.get("display_name"), "kind": "llm",
                    "configured": True, "ok": False,
                    "latency_ms": int((_t.monotonic() - t0) * 1000), "error": str(e)[:200]}

    async def _guard_check(pid: str, provider):
        if not provider.is_configured(config):
            return {"id": pid, "display_name": provider.display_name, "kind": "guardrail",
                    "configured": False, "ok": False, "latency_ms": 0, "error": None}
        t0 = _t.monotonic()
        try:
            status = await provider.check_interaction(
                messages=[{"role": "user", "content": "ping"}],
                cfg=config,
                meta=None,
                system_prompt=None,
            )
            ok = status is not None
            return {"id": pid, "display_name": provider.display_name, "kind": "guardrail",
                    "configured": True, "ok": ok,
                    "latency_ms": int((_t.monotonic() - t0) * 1000), "error": None}
        except Exception as e:
            return {"id": pid, "display_name": provider.display_name, "kind": "guardrail",
                    "configured": True, "ok": False,
                    "latency_ms": int((_t.monotonic() - t0) * 1000), "error": str(e)[:200]}

    # Exclude operator-disabled providers from the health roll-up — they're
    # intentionally turned off so reporting them as "down" is noise.
    disabled = set(getattr(config, "disabled_providers", None) or [])
    llm_tasks = [_llm_check(pid) for pid in PROVIDERS.keys() if pid not in disabled]
    guard_tasks = [_guard_check(pid, p) for pid, p in GUARDRAIL_PROVIDERS.items() if pid not in disabled]
    results = await asyncio.gather(*(llm_tasks + guard_tasks), return_exceptions=False)
    return {"providers": results}


@router.post("/api/chat/compare-llms", dependencies=[Depends(_auth.require_admin)])
async def compare_llms(payload: dict, db: Session = Depends(get_db)):
    """Run the same prompt through multiple LLM providers (each with its own
    model + key as configured in AppConfig) and return per-provider response,
    latency, tokens, and estimated cost. Sequential per provider to keep memory
    use low, but each call honours the same /api/chat path so guardrails and
    tools still fire.

    Body: { message: str, providers: [{provider, model}], session_id?: str }
    """
    from ..providers import PROVIDERS

    message = (payload or {}).get("message") or ""
    requested = (payload or {}).get("providers") or []
    if not message.strip():
        raise HTTPException(status_code=400, detail="message is required")
    if not isinstance(requested, list) or not requested:
        raise HTTPException(status_code=400, detail="providers must be a non-empty list")

    config = db.query(AppConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration found")

    async def _run_one(p: dict):
        pid = (p or {}).get("provider")
        model = (p or {}).get("model")
        if not pid or pid not in PROVIDERS:
            return {"provider": pid, "model": model, "error": f"unknown provider {pid}"}
        # Build a one-off cfg override so we use this provider's key/model
        # without mutating the row.
        override = _ConfigOverride(config, llm_provider=pid, openai_model=model or config.openai_model)
        t0 = _t.monotonic()
        try:
            messages = []
            if config.system_prompt:
                messages.append({"role": "system", "content": config.system_prompt})
            messages.append({"role": "user", "content": message})
            resp = llm_client.chat_completion(
                messages=messages,
                model=model or config.openai_model,
                temperature=config.temperature,
                config=override,
            )
            in_t, out_t = cost_module.extract_token_usage(resp)
            cost = cost_module.estimate_cost_usd(pid, model, in_t, out_t)
            text_ = ((resp or {}).get("choices") or [{}])[0].get("message", {}).get("content") or ""
            return {
                "provider": pid,
                "display_name": PROVIDERS[pid].get("display_name"),
                "model": model,
                "response": text_,
                "latency_ms": int((_t.monotonic() - t0) * 1000),
                "input_tokens": in_t,
                "output_tokens": out_t,
                "cost_usd": cost,
                "error": None,
            }
        except Exception as e:
            return {
                "provider": pid,
                "display_name": PROVIDERS.get(pid, {}).get("display_name"),
                "model": model,
                "response": None,
                "latency_ms": int((_t.monotonic() - t0) * 1000),
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": None,
                "error": str(e),
            }

    results = await asyncio.gather(*[_run_one(p) for p in requested])
    return {"message": message, "results": results}


@router.post("/api/chat/compare-guardrails", dependencies=[Depends(_auth.require_admin)])
async def compare_guardrails(request: ChatRequest, db: Session = Depends(get_db)):
    """Run the user's message through every configured guardrail provider in
    parallel and return per-provider verdicts (with latency).

    Used by the Admin → Compare matrix to show how each vendor sees the same
    payload. Does NOT call the LLM — guardrail check only."""
    from ..guardrail_provider import GUARDRAIL_PROVIDERS

    config = db.query(AppConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration found")
    if not (request.message or "").strip():
        raise HTTPException(status_code=400, detail="message is required")

    msgs = [{"role": "user", "content": request.message}]

    async def _run_one(pid: str, provider):
        if not provider.is_configured(config):
            return {
                "provider": pid,
                "display_name": provider.display_name,
                "configured": False,
                "status": None,
                "latency_ms": 0,
                "error": None,
                "warnings": [],
            }
        t0 = _t.monotonic()
        try:
            status = await provider.check_interaction(
                messages=msgs,
                cfg=config,
                meta={"session_id": request.session_id} if request.session_id else None,
                system_prompt=config.system_prompt,
            )
            warnings: List[str] = []
            # Provider returned nothing despite being configured — almost
            # always an internal failure (rate limit, auth, DNS) that the
            # provider swallowed. Surface it as a warning so the operator
            # doesn't mistake it for a clean pass.
            if status is None:
                warnings.append(
                    "Provider returned no result; likely an internal error. "
                    "Check backend logs."
                )
            else:
                # Providers can flag partial-upstream-failure via metadata
                # (Azure currently does this when text:analyze succeeds but
                # shieldPrompt fails, or vice versa).
                meta_warnings = (status.get("metadata") or {}).get("partial_failure") or []
                if isinstance(meta_warnings, list):
                    warnings.extend(str(w) for w in meta_warnings)
            return {
                "provider": pid,
                "display_name": provider.display_name,
                "configured": True,
                "status": status,
                "latency_ms": int((_t.monotonic() - t0) * 1000),
                "error": None,
                "warnings": warnings,
            }
        except Exception as e:
            return {
                "provider": pid,
                "display_name": provider.display_name,
                "configured": True,
                "status": None,
                "latency_ms": int((_t.monotonic() - t0) * 1000),
                "error": str(e),
                "warnings": [],
            }

    # Skip operator-disabled providers — exact same reasoning as the health
    # endpoint: "disabled" means "stop showing me this".
    disabled = set(getattr(config, "disabled_providers", None) or [])
    tasks = [_run_one(pid, p) for pid, p in GUARDRAIL_PROVIDERS.items() if pid not in disabled]
    results = await asyncio.gather(*tasks)
    return {"message": request.message, "results": results}


@router.post("/api/moderation/image", dependencies=[Depends(_auth.require_admin)])
async def moderate_image(payload: dict, db: Session = Depends(get_db)):
    """Scan an image with the active guardrail provider.

    Body: { "image_data_url": "data:image/png;base64,..." }
    Returns the same Lakera-shaped status the chat path uses, with an extra
    `supported: bool` so the UI can show a clear "not supported by this
    provider" badge instead of an empty result.
    """
    from ..guardrail_provider import GUARDRAIL_PROVIDERS, active_provider_id

    image_data_url = (payload or {}).get("image_data_url")
    if not image_data_url:
        raise HTTPException(status_code=400, detail="image_data_url is required")
    config = db.query(AppConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration found")
    pid = active_provider_id(config)
    provider = GUARDRAIL_PROVIDERS.get(pid)
    if not provider:
        raise HTTPException(status_code=400, detail=f"No guardrail provider configured ({pid})")
    if not provider.is_configured(config):
        raise HTTPException(status_code=400, detail=f"Guardrail provider {pid} missing credentials")
    if not getattr(provider, "supports_image", False):
        return {
            "supported": False,
            "provider": pid,
            "status": {
                "flagged": False,
                "breakdown": [],
                "payload": [],
                "metadata": {"source": pid, "skipped": "image_moderation_not_supported"},
            },
        }
    status = await provider.check_image(image_data_url, config)
    return {"supported": True, "provider": pid, "status": status}


@router.post("/api/playground/run", dependencies=[Depends(_auth.require_admin)])
async def playground_run(payload: dict, db: Session = Depends(get_db)):
    """Interactive bench: run one prompt (+ optional images) through a chosen
    LLM model + guardrail provider, without mutating the saved config or
    polluting conversation history / audit log. Supports multi-turn chat via
    a client-supplied `history` (the caller owns it; nothing is persisted).

    Body: { message, images?: [base64], model?, guardrail_provider?,
            guardrail_enabled?: bool, history?: [{role, content}] }
    Returns: { response, lakera, ocr_texts, model, guardrail_provider, guardrail_enabled }
    """
    from ..agent import AgentRequest, run_agent

    config = db.query(AppConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration found")

    message = (payload or {}).get("message") or ""
    images = (payload or {}).get("images") or None
    history = (payload or {}).get("history") or None
    if not message.strip() and not images:
        raise HTTPException(status_code=400, detail="message or images required")

    model = (payload or {}).get("model") or config.openai_model
    guardrail = (payload or {}).get("guardrail_provider") or getattr(config, "guardrail_provider", None)
    guardrail_enabled = bool((payload or {}).get("guardrail_enabled", True))

    overrides: Dict[str, Any] = {
        "openai_model": model,
        "lakera_enabled": guardrail_enabled,
    }
    if guardrail:
        overrides["guardrail_provider"] = guardrail
    cfg = _ConfigOverride(config, **overrides)

    req = AgentRequest(message=message, images=images, history=history)
    result = await run_agent(req, cfg, db, persist=False)

    return {
        "response": result.response,
        "lakera": result.lakera_status,
        "ocr_texts": result.ocr_texts,
        "model": model,
        "guardrail_provider": guardrail if guardrail_enabled else None,
        "guardrail_enabled": guardrail_enabled,
    }
