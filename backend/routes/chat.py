"""Chat endpoints. Three flavors:

  /api/chat          — non-streaming, full agent loop (RAG + tools + post-guard)
  /api/chat/stream   — SSE token streaming; pre-guard runs before tokens,
                       post-guard after. No tools in the stream path.
  /api/chat/compare  — runs the same prompt twice (guardrail on / off) for
                       the landing-page comparison modal.
"""

import asyncio
import json
import time as _time
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import audit, llm_capabilities, llm_client
from ..agent import AgentRequest, run_agent
from ..database import get_db
from ..models import AppConfig, DemoPrompt, Message
from ..schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    # Get configuration
    config = db.query(AppConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration found")

    # If sent from a demo prompt suggestion with a preferred LLM, switch model permanently
    if request.prompt_id:
        demo_prompt = db.query(DemoPrompt).filter(DemoPrompt.id == request.prompt_id).first()
        if demo_prompt and demo_prompt.preferred_llm:
            valid_models = llm_client.get_models(config)
            if valid_models and demo_prompt.preferred_llm in valid_models:
                config.openai_model = demo_prompt.preferred_llm
                db.commit()
            elif valid_models and config.openai_model not in valid_models:
                config.openai_model = valid_models[0]
                db.commit()

    llm_client.ensure_active_model_valid(config, db)

    # Short-circuit images against known text-only models — the upstream
    # gateway would otherwise return an opaque "request body must be valid
    # JSON" error that doesn't tell the operator anything actionable.
    if request.images and llm_capabilities.is_known_text_only(config.openai_model):
        raise HTTPException(
            status_code=400,
            detail=llm_capabilities.reject_image_request_message(config.openai_model),
        )

    # Create agent request
    agent_request = AgentRequest(
        message=request.message,
        session_id=request.session_id,
        conversation_id=request.conversation_id,
        images=request.images,
    )

    # Run agent
    result = await run_agent(agent_request, config, db)

    return ChatResponse(
        response=result.response,
        lakera=result.lakera_status,
        tool_traces=result.tool_traces,
        citations=result.citations,
        conversation_id=result.conversation_id,
    )


@router.post("/stream")
async def chat_stream(request: ChatRequest, db: Session = Depends(get_db)):
    """SSE streaming chat. Pre-guardrail runs before tokens; if blocked, emits
    a single 'blocked' event and closes. Otherwise streams 'chunk' events,
    then a final 'done' event with lakera+conversation_id+tool_traces."""
    from ..agent import _ensure_conversation, _load_conversation_history
    from ..guardrail_provider import active_provider_id as _active_gid
    from ..guardrail_provider import resolve_provider as _resolve_provider
    from ..providers import provider_id as _llm_pid

    config = db.query(AppConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration found")
    llm_client.ensure_active_model_valid(config, db)

    # Short-circuit images against known text-only models. Emitted as an
    # SSE `error` event (same channel ChatWidget already listens on for
    # upstream failures) so the UX path is the same — just with a useful
    # message instead of "OpenAIException - request body must be valid JSON".
    _reject_msg = None
    if request.images and llm_capabilities.is_known_text_only(config.openai_model):
        _reject_msg = llm_capabilities.reject_image_request_message(config.openai_model)

    async def event_stream():
        if _reject_msg:
            yield f"event: error\ndata: {json.dumps({'message': _reject_msg})}\n\n"
            return
        start_t = _time.monotonic()
        conv = _ensure_conversation(db, request.conversation_id, request.session_id, request.message)
        history = _load_conversation_history(db, conv.id)

        # Pre-guardrail
        guardrail_pid = _active_gid(config) if config.lakera_enabled else None
        active_guardrail = _resolve_provider(config) if config.lakera_enabled else None
        pre_status = None
        if active_guardrail:
            pre_status = await active_guardrail.check_interaction(
                messages=[{"role": "user", "content": request.message}],
                cfg=config,
                meta={"session_id": request.session_id} if request.session_id else None,
                system_prompt=config.system_prompt,
            )
            if pre_status and pre_status.get("flagged") and config.lakera_blocking_mode:
                blocked_text = "This content has been moderated and found to be in breach of our security policies."
                db.add(Message(conversation_id=conv.id, role="user", content=request.message,
                               flagged=True, guardrail_status=pre_status))
                db.add(Message(conversation_id=conv.id, role="assistant", content=blocked_text,
                               flagged=True, guardrail_status=pre_status))
                db.commit()
                audit.record_chat_turn(
                    db,
                    user_message=request.message,
                    assistant_response=blocked_text,
                    conversation_id=conv.id,
                    session_id=request.session_id,
                    llm_provider=_llm_pid(config),
                    llm_model=config.openai_model,
                    guardrail_provider=guardrail_pid,
                    guardrail_status=pre_status,
                    latency_ms=int((_time.monotonic() - start_t) * 1000),
                    blocked=True,
                )
                yield f"event: blocked\ndata: {json.dumps({'lakera': pre_status, 'conversation_id': conv.id})}\n\n"
                return

        # Build messages (no tools in stream path)
        from ..agent import _user_content
        messages: List[Dict[str, Any]] = []
        if config.system_prompt:
            messages.append({"role": "system", "content": config.system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": _user_content(request.message, request.images)})

        # Stream the LLM
        full_text_parts: List[str] = []
        try:
            loop = asyncio.get_event_loop()
            def _gen():
                return llm_client.chat_completion_stream(
                    messages=messages,
                    model=config.openai_model,
                    temperature=config.temperature,
                    config=config,
                )

            gen = await loop.run_in_executor(None, _gen)
            for token in gen:
                if not token:
                    continue
                full_text_parts.append(token)
                yield f"event: chunk\ndata: {json.dumps({'text': token})}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
            return

        response_text = "".join(full_text_parts)

        # Post-guardrail
        post_status = None
        if active_guardrail:
            post_status = await active_guardrail.check_interaction(
                messages=[
                    {"role": "user", "content": request.message},
                    {"role": "assistant", "content": response_text},
                ],
                cfg=config,
                meta={"session_id": request.session_id} if request.session_id else None,
                system_prompt=config.system_prompt,
            )
            if post_status and post_status.get("flagged") and config.lakera_blocking_mode:
                response_text = "This content has been moderated and found to be in breach of our security policies."

        # Persist conversation + audit
        db.add(Message(conversation_id=conv.id, role="user", content=request.message,
                       flagged=False, guardrail_status=None))
        db.add(Message(conversation_id=conv.id, role="assistant", content=response_text,
                       flagged=bool(post_status and post_status.get("flagged")),
                       guardrail_status=post_status))
        db.commit()
        audit.record_chat_turn(
            db,
            user_message=request.message,
            assistant_response=response_text,
            conversation_id=conv.id,
            session_id=request.session_id,
            llm_provider=_llm_pid(config),
            llm_model=config.openai_model,
            guardrail_provider=guardrail_pid,
            guardrail_status=post_status,
            latency_ms=int((_time.monotonic() - start_t) * 1000),
            blocked=False,
        )

        yield f"event: done\ndata: {json.dumps({'lakera': post_status, 'conversation_id': conv.id, 'response': response_text})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


from .._config_override import ConfigOverride as _ConfigOverride  # noqa: E402


@router.post("/compare")
async def chat_compare(request: ChatRequest, db: Session = Depends(get_db)):
    """Run the same prompt twice — once with the active guardrail on, once
    off — and return both results side-by-side. Works for every guardrail
    provider (Lakera / OpenAI Moderation / Bedrock / Azure / Palo Alto AIRS
    / Cloudflare Firewall for AI); the active one is whatever is selected
    in Admin → Security. The response includes the provider id + display
    name so the UI can label panes correctly."""
    from ..guardrail_provider import GUARDRAIL_PROVIDERS, active_provider_id, resolve_provider

    config = db.query(AppConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration found")

    pid = active_provider_id(config)
    provider_obj = GUARDRAIL_PROVIDERS.get(pid)
    if not resolve_provider(config):
        name = provider_obj.display_name if provider_obj else pid
        raise HTTPException(
            status_code=400,
            detail=f"Comparison requires the active guardrail provider ({name}) to be configured. "
                   f"Set its credentials in Admin → Security, or switch the guardrail provider.",
        )

    llm_client.ensure_active_model_valid(config, db)
    agent_request = AgentRequest(message=request.message, session_id=request.session_id)

    # `lakera_enabled` is the master "guardrail enabled" toggle (legacy field
    # name kept for backwards-compat); flipping it disables every provider, not
    # just Lakera.
    cfg_with = _ConfigOverride(config, lakera_enabled=True)
    cfg_without = _ConfigOverride(config, lakera_enabled=False)

    # Don't pollute audit log / conversation history with the off-side run.
    result_with = await run_agent(agent_request, cfg_with, db, persist=False)
    result_without = await run_agent(agent_request, cfg_without, db, persist=False)

    return {
        "guardrail_provider": pid,
        "guardrail_display_name": provider_obj.display_name if provider_obj else pid,
        "with_guard": {
            "response": result_with.response,
            # `lakera` key kept for frontend backwards-compat; payload is the
            # active provider's Lakera-shaped status dict.
            "lakera": result_with.lakera_status,
            "tool_traces": result_with.tool_traces,
            "citations": result_with.citations,
        },
        "without_guard": {
            "response": result_without.response,
            "lakera": None,
            "tool_traces": result_without.tool_traces,
            "citations": result_without.citations,
        },
    }
