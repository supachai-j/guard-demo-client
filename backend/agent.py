import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import audit, costs, lakera, llm_client, rag, toolhive, webhooks
from .guardrail_provider import active_provider_id, resolve_provider
from .models import AppConfig, Conversation, Message
from .providers import provider_id as llm_provider_id


class AgentRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    conversation_id: Optional[int] = None
    # Base64 data URLs (data:image/png;base64,...) for vision-capable models.
    # Guardrails scan the text `message` only; images pass through to the LLM.
    images: Optional[List[str]] = None
    # Client-supplied prior turns ([{role, content}, ...]) for stateless
    # multi-turn chat (Playground). Used only when persist=False — the caller
    # owns the history instead of the DB, so nothing is saved. Ignored when
    # persist=True, where history comes from the Conversation row instead.
    history: Optional[List[Dict[str, Any]]] = None


def _user_content(message: str, images: Optional[List[str]]):
    """Build the user message content. Plain string when no images; OpenAI
    vision content-block list when images are present. LiteLLM translates the
    block format to each provider's native vision schema.

    Anthropic rejects empty text blocks ("text content blocks must be
    non-empty"), so the text block is omitted when the message is blank —
    image-only content is valid."""
    if not images:
        return message
    blocks: List[Dict[str, Any]] = []
    if message and message.strip():
        blocks.append({"type": "text", "text": message})
    for url in images:
        if url:
            blocks.append({"type": "image_url", "image_url": {"url": url}})
    return blocks


class AgentResult(BaseModel):
    response: str
    citations: List[Dict[str, Any]] = []
    tool_traces: List[Dict[str, Any]] = []
    lakera_status: Optional[Dict[str, Any]] = None
    conversation_id: Optional[int] = None
    # Text OCR'd from any attached images (for Playground / transparency).
    ocr_texts: List[str] = []


def _load_conversation_history(db: Session, conversation_id: Optional[int], limit: int = 10) -> List[Dict[str, Any]]:
    """Return the last `limit` (user, assistant) turns formatted for the LLM."""
    if not conversation_id:
        return []
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(limit * 2)
        .all()
    )
    rows.reverse()
    return [{"role": r.role, "content": r.content} for r in rows]


def _ensure_conversation(db: Session, conversation_id: Optional[int], session_id: Optional[str], seed_title: str) -> Conversation:
    if conversation_id:
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if conv:
            return conv
    conv = Conversation(
        title=(seed_title or "New conversation")[:80],
        session_id=session_id,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


async def run_agent(req: AgentRequest, cfg: AppConfig, db: Session, *, persist: bool = True) -> AgentResult:
    """
    Main orchestrator function that coordinates RAG, tools, and OpenAI.

    persist=False is used by compare flows that want a clean run without
    appending to conversation history / audit log (e.g. /api/chat/compare).
    """
    _start_t = time.monotonic()
    # Step 0: Check user input with the active guardrail provider (pre-response check).
    # `lakera_enabled` is the master "guardrail enabled" toggle (legacy name);
    # `lakera_blocking_mode` is the "block vs monitor" switch — they apply to ALL providers.
    lakera_api_key = cfg.lakera_api_key if cfg.lakera_enabled else None
    lakera_project_id = cfg.lakera_project_id if cfg.lakera_enabled else None
    lakera_blocking_mode = cfg.lakera_blocking_mode if cfg.lakera_enabled else False
    guardrail_provider_id = active_provider_id(cfg) if cfg.lakera_enabled else None
    active_guardrail = resolve_provider(cfg) if cfg.lakera_enabled else None
    # LiteLLM-native guardrails only engage when (a) using the LiteLLM proxy AND
    # (b) the active guardrail provider is still Lakera — other providers don't
    # have a corresponding LiteLLM-native equivalent in this codebase.
    use_litellm_guardrails = bool(
        getattr(cfg, "use_litellm", False)
        and cfg.lakera_enabled
        and cfg.lakera_api_key
        and guardrail_provider_id == "lakera"
    )
    litellm_guardrail_block = (
        (getattr(cfg, "litellm_guardrail_name", None) or "").strip() or "lakera-guard-block"
    )
    litellm_guardrail_monitor = (
        (getattr(cfg, "litellm_guardrail_monitor_name", None) or "").strip() or "lakera-guard-monitor"
    )
    litellm_guardrail = litellm_guardrail_block if lakera_blocking_mode else litellm_guardrail_monitor
    litellm_guardrail_metadata = (
        {
            "session_id": req.session_id or "",
            "guardrail_name": litellm_guardrail,
            "source": "agentic-demo-chat",
        }
        if use_litellm_guardrails
        else None
    )

    # Multi-turn memory: when persisting, history comes from the Conversation
    # row. When not persisting (Playground), the client owns the history and
    # passes prior turns inline so nothing touches the DB.
    conv = None
    history: List[Dict[str, Any]] = []
    if persist:
        conv = _ensure_conversation(db, req.conversation_id, req.session_id, req.message)
        history = _load_conversation_history(db, conv.id)
    elif req.history:
        # Keep only well-formed {role, content} text turns. Blank content is
        # dropped: Anthropic rejects empty text blocks ("text content blocks
        # must be non-empty"), which an image-only prior turn would otherwise
        # produce. The client sends an "[image]" placeholder for those, but we
        # guard here too so a malformed history can't crash the LLM call.
        history = [
            {"role": h["role"], "content": h["content"]}
            for h in req.history
            if isinstance(h, dict)
            and h.get("role") in ("user", "assistant")
            and isinstance(h.get("content"), str)
            and h["content"].strip()
        ]

    active_llm_pid = llm_provider_id(cfg)

    # Image-injection pre-scan (§4.3.14): OCR any attached images and fold the
    # extracted text into what the guardrail sees, so injection embedded in an
    # image is caught before the prompt reaches the LLM. Text-only guardrails
    # can't read images; this is the SI OCR stage in front of them.
    guard_input_text = req.message
    ocr_texts: List[str] = []
    if req.images and cfg.lakera_enabled and active_guardrail and not use_litellm_guardrails:
        from . import ocr
        for _img in req.images:
            try:
                _txt = await ocr.extract_text_from_image(_img, cfg)
            except Exception:  # noqa: BLE001
                _txt = ""
            if _txt:
                ocr_texts.append(_txt)
                guard_input_text = f"{guard_input_text}\n{_txt}".strip() if guard_input_text else _txt

    if cfg.lakera_enabled and active_guardrail and not use_litellm_guardrails:
        provider_name = active_guardrail.display_name
        print(f"🛡️ Checking user input with {provider_name}...")
        # Pre-check messages: user text + OCR-extracted image text (image injection).
        pre_check_messages = [{"role": "user", "content": guard_input_text}]

        lakera_result = await active_guardrail.check_interaction(
            messages=pre_check_messages,
            cfg=cfg,
            meta={"session_id": req.session_id} if req.session_id else None,
            system_prompt=cfg.system_prompt,
        )

        if lakera_result and lakera_result.get("flagged"):
            print(f"⚠️ User input flagged by {provider_name}: {lakera_result.get('breakdown', [])}")
            if lakera_blocking_mode:
                print(f"🚫 User input blocked by {provider_name} (blocking mode enabled)")
                blocked_text = "This content has been moderated and found to be in breach of our security policies. Please contact support if you believe this is an error."
                if persist and conv is not None:
                    db.add(Message(conversation_id=conv.id, role="user", content=req.message,
                                   flagged=True, guardrail_status=lakera_result))
                    db.add(Message(conversation_id=conv.id, role="assistant", content=blocked_text,
                                   flagged=True, guardrail_status=lakera_result))
                    db.commit()
                    audit.record_chat_turn(
                        db,
                        user_message=req.message,
                        assistant_response=blocked_text,
                        conversation_id=conv.id,
                        session_id=req.session_id,
                        llm_provider=active_llm_pid,
                        llm_model=cfg.openai_model,
                        guardrail_provider=guardrail_provider_id,
                        guardrail_status=lakera_result,
                        tool_traces=[],
                        latency_ms=int((time.monotonic() - _start_t) * 1000),
                        blocked=True,
                    )
                return AgentResult(
                    response=blocked_text,
                    citations=[],
                    tool_traces=[],
                    lakera_status=lakera_result,
                    conversation_id=conv.id if conv else None,
                    ocr_texts=ocr_texts,
                )
            else:
                print(f"📝 User input flagged by {provider_name} but allowed through (monitor mode)")
        else:
            print(f"✅ User input passed {provider_name} moderation")

    # Step 1: Get context from RAG
    context = await rag.retrieve(req.message)
    citations = []
    if context:
        citations = [
            {"source": doc.get("metadata", {}).get("source")}
            for doc in context
            if doc.get("metadata", {}).get("source") and doc.get("metadata", {}).get("source") != "unknown"
        ]

    # Step 2: Get tools manifest for OpenAI
    tools_manifest = toolhive.openai_tools_manifest(db)
    # Step 3: Prepare messages for OpenAI
    messages = []

    # Add system prompt
    if cfg.system_prompt:
        messages.append({"role": "system", "content": cfg.system_prompt})

    # Add context if available
    if context:
        context_text = "\n\n".join([doc["text"] for doc in context])
        messages.append({"role": "system", "content": f"Context information:\n{context_text}"})

    # Multi-turn: replay prior conversation turns (after system prompts, before current user message).
    if history:
        messages.extend(history)

    # Add user message — vision content-block when images attached, else plain text.
    messages.append({"role": "user", "content": _user_content(req.message, req.images)})

    # Step 4: Call LLM with tools
    total_input_tokens = 0
    total_output_tokens = 0
    try:
        response = llm_client.chat_completion(
            messages=messages,
            model=cfg.openai_model,
            temperature=cfg.temperature,
            tools=tools_manifest if tools_manifest else None,
            config=cfg,
            litellm_guardrail_name=litellm_guardrail if use_litellm_guardrails else None,
            litellm_metadata=litellm_guardrail_metadata,
        )
        _in, _out = costs.extract_token_usage(response)
        total_input_tokens += _in
        total_output_tokens += _out

        # Extract the response
        assistant_message = response["choices"][0]["message"]
        messages.append(assistant_message)  # Add assistant message to conversation

        # Initialize tool traces
        tool_traces = []

        # Handle tool calls if any
        if assistant_message.get("tool_calls"):
            print(f"🔧 OpenAI requested {len(assistant_message['tool_calls'])} tool calls")

            # Execute each tool call
            for tool_call in assistant_message["tool_calls"]:
                tool_name = tool_call["function"]["name"]
                tool_args = tool_call["function"]["arguments"]
                tool_call_id = tool_call["id"]

                print(f"🔧 Executing tool: {tool_name} with args: {tool_args}")

                # Parse arguments
                import json

                try:
                    parsed_args = json.loads(tool_args)
                except json.JSONDecodeError:
                    parsed_args = {}

                # Find the tool metadata from the manifest
                tool_metadata = None
                for tool_def in tools_manifest:
                    if tool_def["function"]["name"] == tool_name:
                        tool_metadata = tool_def.get("_tool_metadata")
                        break

                if not tool_metadata:
                    tool_result = {
                        "status": "error",
                        "content_string": f"Tool metadata not found for: {tool_name}",
                        "raw_result": None,
                    }
                else:
                    # Execute the tool with metadata
                    tool_result = await toolhive.execute(
                        tool_name=tool_name,
                        args=parsed_args,
                        tool_metadata=tool_metadata,
                        db=db,
                        lakera_api_key=lakera_api_key,
                        lakera_project_id=lakera_project_id,
                        lakera_blocking_mode=lakera_blocking_mode,
                    )

                # Add tool result as role: "tool" message
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": tool_result["content_string"],
                    }
                )

                # Add to tool traces
                tool_traces.append({"id": tool_call_id, "name": tool_name, "args": parsed_args, "result": tool_result})

            # Make second call to LLM with tool results
            print("🔧 Making follow-up call to LLM with tool results")
            final_response = llm_client.chat_completion(
                messages=messages,
                model=cfg.openai_model,
                temperature=cfg.temperature,
                config=cfg,
                litellm_guardrail_name=litellm_guardrail if use_litellm_guardrails else None,
                litellm_metadata=litellm_guardrail_metadata,
            )
            _in, _out = costs.extract_token_usage(final_response)
            total_input_tokens += _in
            total_output_tokens += _out

            # Get final response
            final_assistant_message = final_response["choices"][0]["message"]
            response_text = final_assistant_message["content"]
        else:
            # No tool calls, use the original response
            response_text = assistant_message["content"]

        # Step 5: Check assistant response with the active guardrail (post-response check)
        lakera_status = None
        if cfg.lakera_enabled and active_guardrail and not use_litellm_guardrails:
            provider_name = active_guardrail.display_name
            print(f"🛡️ Checking assistant response with {provider_name}...")
            post_messages = [
                {"role": "user", "content": req.message},
                {"role": "assistant", "content": response_text or ""},
            ]

            lakera_status = await active_guardrail.check_interaction(
                messages=post_messages,
                cfg=cfg,
                meta={"session_id": req.session_id} if req.session_id else None,
                system_prompt=cfg.system_prompt,
            )

            if lakera_status and lakera_status.get("flagged"):
                print(f"⚠️ Assistant response flagged by {provider_name}: {lakera_status.get('breakdown', [])}")
                if lakera_blocking_mode:
                    print(f"🚫 Assistant response blocked by {provider_name} (blocking mode)")
                    response_text = "This content has been moderated and found to be in breach of our security policies. Please contact support if you believe this is an error."
                else:
                    print(f"📝 Assistant response flagged by {provider_name} but allowed through (monitor mode)")
            else:
                print(f"✅ Assistant response passed {provider_name} moderation")
        elif (
            cfg.lakera_enabled
            and cfg.lakera_api_key
            and use_litellm_guardrails
            and not lakera_blocking_mode
        ):
            # In monitor mode with LiteLLM guardrails, pull detector confidence data for the UI panel.
            lakera_status = await lakera.get_guard_results_for_ui(
                messages=[
                    {"role": "user", "content": req.message},
                    {"role": "assistant", "content": response_text or ""},
                ],
                meta={"session_id": req.session_id} if req.session_id else None,
                api_key=cfg.lakera_api_key,
                project_id=cfg.lakera_project_id,
                system_prompt=cfg.system_prompt,
            )
        elif cfg.lakera_enabled and cfg.lakera_api_key and use_litellm_guardrails:
            # LiteLLM blocking mode only returns Lakera details when content is blocked.
            # For successful turns, clear any stale previous red state in the UI.
            lakera_status = {"flagged": False, "breakdown": [], "payload": [], "metadata": {"source": "litellm"}}
            lakera.set_last_result(lakera_status)

        if cfg.lakera_enabled and cfg.lakera_api_key and use_litellm_guardrails and lakera_status is None:
            # Fallback clear for monitor mode when /guard/results is unavailable.
            lakera_status = {"flagged": False, "breakdown": [], "payload": [], "metadata": {"source": "litellm"}}
            lakera.set_last_result(lakera_status)

        cost_usd = costs.estimate_cost_usd(
            active_llm_pid, cfg.openai_model, total_input_tokens, total_output_tokens
        )
        if persist and conv is not None:
            db.add(Message(conversation_id=conv.id, role="user", content=req.message,
                           flagged=False, guardrail_status=None))
            db.add(Message(conversation_id=conv.id, role="assistant", content=response_text or "",
                           flagged=bool(lakera_status and lakera_status.get("flagged")),
                           guardrail_status=lakera_status))
            db.commit()
            audit.record_chat_turn(
                db,
                user_message=req.message,
                assistant_response=response_text,
                conversation_id=conv.id,
                session_id=req.session_id,
                llm_provider=active_llm_pid,
                llm_model=cfg.openai_model,
                guardrail_provider=guardrail_provider_id,
                guardrail_status=lakera_status,
                tool_traces=tool_traces,
                latency_ms=int((time.monotonic() - _start_t) * 1000),
                blocked=False,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cost_usd=cost_usd,
            )
            # Fire-and-forget webhook on flag
            if lakera_status and lakera_status.get("flagged"):
                await webhooks.fire_flagged_event(
                    cfg,
                    user_message=req.message,
                    assistant_response=response_text,
                    guardrail_status=lakera_status,
                    session_id=req.session_id,
                    conversation_id=conv.id,
                )

        return AgentResult(
            response=response_text,
            citations=citations,
            tool_traces=tool_traces,
            lakera_status=lakera_status,
            conversation_id=conv.id if conv else None,
            ocr_texts=ocr_texts,
        )

    except llm_client.LiteLLMGuardrailError as e:
        lakera_status = e.lakera_status if isinstance(e.lakera_status, dict) else None
        if lakera_status:
            lakera.set_last_result(lakera_status)
        # Surface the active provider's display name in the user-facing block
        # message rather than hardcoding "Lakera" — the chat may be running
        # behind Bedrock, Azure, Prisma AIRS, Cloudflare, etc.
        _provider_label = (
            active_guardrail.display_name if active_guardrail else "the active guardrail"
        )
        blocked_text = (
            f"This content has been moderated by {_provider_label} and found to be in "
            "breach of our security policies. Please contact support if you believe this is an error."
        )
        if persist and conv is not None:
            try:
                audit.record_chat_turn(
                    db,
                    user_message=req.message,
                    assistant_response=blocked_text,
                    conversation_id=conv.id,
                    session_id=req.session_id,
                    llm_provider=active_llm_pid,
                    llm_model=cfg.openai_model,
                    guardrail_provider=guardrail_provider_id,
                    guardrail_status=lakera_status,
                    tool_traces=tool_traces if "tool_traces" in locals() else [],
                    latency_ms=int((time.monotonic() - _start_t) * 1000),
                    blocked=True,
                )
            except Exception:
                pass
        return AgentResult(
            response=blocked_text,
            citations=citations,
            tool_traces=tool_traces if "tool_traces" in locals() else [],
            lakera_status=lakera_status,
            conversation_id=conv.id if conv else None,
        )
    except Exception as e:
        err_text = f"I apologize, but I encountered an error: {str(e)}"
        if persist and conv is not None:
            try:
                audit.record_chat_turn(
                    db,
                    user_message=req.message,
                    assistant_response=err_text,
                    conversation_id=conv.id,
                    session_id=req.session_id,
                    llm_provider=active_llm_pid,
                    llm_model=cfg.openai_model,
                    guardrail_provider=guardrail_provider_id,
                    tool_traces=tool_traces if "tool_traces" in locals() else [],
                    latency_ms=int((time.monotonic() - _start_t) * 1000),
                    error=str(e),
                )
            except Exception:
                pass
        return AgentResult(
            response=err_text,
            citations=citations,
            tool_traces=tool_traces if "tool_traces" in locals() else [],
            lakera_status=None,
            conversation_id=conv.id if conv else None,
        )
