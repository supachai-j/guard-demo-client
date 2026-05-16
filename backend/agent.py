from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import lakera, llm_client, rag, toolhive
from .guardrail_provider import active_provider_id, resolve_provider
from .models import AppConfig


class AgentRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class AgentResult(BaseModel):
    response: str
    citations: List[Dict[str, Any]] = []
    tool_traces: List[Dict[str, Any]] = []
    lakera_status: Optional[Dict[str, Any]] = None


async def run_agent(req: AgentRequest, cfg: AppConfig, db: Session) -> AgentResult:
    """
    Main orchestrator function that coordinates RAG, tools, and OpenAI
    """
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

    if cfg.lakera_enabled and active_guardrail and not use_litellm_guardrails:
        provider_name = active_guardrail.display_name
        print(f"🛡️ Checking user input with {provider_name}...")
        # Pre-check messages: user only (system prompt added inside the provider if needed)
        pre_check_messages = [{"role": "user", "content": req.message}]

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
                return AgentResult(
                    response="This content has been moderated and found to be in breach of our security policies. Please contact support if you believe this is an error.",
                    citations=[],
                    tool_traces=[],
                    lakera_status=lakera_result,
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

    # Add user message
    messages.append({"role": "user", "content": req.message})

    # Step 4: Call LLM with tools
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

        return AgentResult(
            response=response_text, citations=citations, tool_traces=tool_traces, lakera_status=lakera_status
        )

    except llm_client.LiteLLMGuardrailError as e:
        lakera_status = e.lakera_status if isinstance(e.lakera_status, dict) else None
        if lakera_status:
            lakera.set_last_result(lakera_status)
        return AgentResult(
            response="This content has been moderated by Lakera and found to be in breach of our security policies. Please contact support if you believe this is an error.",
            citations=citations,
            tool_traces=tool_traces if "tool_traces" in locals() else [],
            lakera_status=lakera_status,
        )
    except Exception as e:
        return AgentResult(
            response=f"I apologize, but I encountered an error: {str(e)}",
            citations=citations,
            tool_traces=tool_traces if "tool_traces" in locals() else [],
            lakera_status=None,
        )
