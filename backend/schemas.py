from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# Config schemas
class AppConfigBase(BaseModel):
    business_name: Optional[str] = None
    tagline: Optional[str] = None
    hero_text: Optional[str] = None
    hero_image_url: Optional[str] = None
    logo_url: Optional[str] = None
    lakera_enabled: bool = True
    lakera_blocking_mode: bool = False
    use_litellm: bool = False
    litellm_base_url: Optional[str] = None
    litellm_guardrail_name: Optional[str] = None
    litellm_guardrail_monitor_name: Optional[str] = None
    rag_content_scanning: bool = False
    rag_lakera_project_id: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    temperature: int = 7
    system_prompt: Optional[str] = None
    # UI theme: e.g. "blue", "emerald", "purple", "amber"
    theme: Optional[str] = "blue"


class AppConfigResponse(AppConfigBase):
    id: int
    openai_api_key: Optional[str] = None
    litellm_virtual_key: Optional[str] = None
    lakera_api_key: Optional[str] = None
    lakera_project_id: Optional[str] = None
    rag_lakera_project_id: Optional[str] = None
    # Multi-provider fields
    llm_provider: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    mistral_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    together_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    ollama_base_url: Optional[str] = None
    # Multi-guardrail fields
    guardrail_provider: Optional[str] = None
    bedrock_guardrail_id: Optional[str] = None
    bedrock_guardrail_version: Optional[str] = None
    bedrock_region: Optional[str] = None
    bedrock_access_key_id: Optional[str] = None
    bedrock_secret_access_key: Optional[str] = None
    azure_content_safety_endpoint: Optional[str] = None
    azure_content_safety_key: Optional[str] = None
    palo_alto_api_key: Optional[str] = None
    palo_alto_profile_name: Optional[str] = None
    palo_alto_host: Optional[str] = None
    portkey_api_key: Optional[str] = None
    portkey_virtual_key: Optional[str] = None
    portkey_base_url: Optional[str] = None
    thaillm_api_key: Optional[str] = None
    thaillm_base_url: Optional[str] = None
    cloudflare_account_id: Optional[str] = None
    cloudflare_api_token: Optional[str] = None
    cloudflare_gateway_id: Optional[str] = None
    webhook_url: Optional[str] = None
    provider_config_locked: bool = False
    disabled_providers: list = []
    created_at: datetime
    updated_at: datetime


class AppConfigUpdate(AppConfigBase):
    openai_api_key: Optional[str] = None
    litellm_virtual_key: Optional[str] = None
    lakera_api_key: Optional[str] = None
    lakera_project_id: Optional[str] = None
    rag_lakera_project_id: Optional[str] = None
    use_litellm: Optional[bool] = None
    litellm_base_url: Optional[str] = None
    # Multi-provider fields
    llm_provider: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    mistral_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    together_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    ollama_base_url: Optional[str] = None
    # Multi-guardrail fields
    guardrail_provider: Optional[str] = None
    bedrock_guardrail_id: Optional[str] = None
    bedrock_guardrail_version: Optional[str] = None
    bedrock_region: Optional[str] = None
    bedrock_access_key_id: Optional[str] = None
    bedrock_secret_access_key: Optional[str] = None
    azure_content_safety_endpoint: Optional[str] = None
    azure_content_safety_key: Optional[str] = None
    palo_alto_api_key: Optional[str] = None
    palo_alto_profile_name: Optional[str] = None
    palo_alto_host: Optional[str] = None
    portkey_api_key: Optional[str] = None
    portkey_virtual_key: Optional[str] = None
    portkey_base_url: Optional[str] = None
    thaillm_api_key: Optional[str] = None
    thaillm_base_url: Optional[str] = None
    cloudflare_account_id: Optional[str] = None
    cloudflare_api_token: Optional[str] = None
    cloudflare_gateway_id: Optional[str] = None
    webhook_url: Optional[str] = None
    # Demo-safe lock: when True, provider-related fields are read-only via PUT
    # /api/config and POST /api/config/import. Toggle itself always changeable.
    provider_config_locked: Optional[bool] = None
    # Operator-disabled providers (subset of known provider IDs). When a
    # provider's ID is in this list it's excluded from runtime fan-out and
    # cannot be set as active.
    disabled_providers: Optional[list] = None


# Chat schemas
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    prompt_id: Optional[int] = None
    conversation_id: Optional[int] = None


class ChatResponse(BaseModel):
    response: str
    lakera: Optional[Dict[str, Any]] = None
    tool_traces: Optional[List[Dict[str, Any]]] = None
    citations: Optional[List[Dict[str, Any]]] = None
    conversation_id: Optional[int] = None


# RAG schemas
class RagGenerateRequest(BaseModel):
    industry: str
    seed_prompt: str
    preview_only: bool = False


class RagGenerateResponse(BaseModel):
    markdown: str
    ingested: bool = False


class RagSearchResponse(BaseModel):
    chunks: List[Dict[str, Any]]


# Tool schemas
class ToolBase(BaseModel):
    name: str
    description: Optional[str] = None
    endpoint: Optional[str] = None
    type: str = "mcp"
    enabled: bool = True
    config_json: Optional[Dict[str, Any]] = None


class ToolResponse(ToolBase):
    id: int
    created_at: datetime
    updated_at: datetime


class ToolCreate(ToolBase):
    pass


class ToolUpdate(ToolBase):
    pass


# Lakera schemas
class LakeraResult(BaseModel):
    result: Dict[str, Any]
    timestamp: datetime


# Demo Prompt schemas
class DemoPromptBase(BaseModel):
    title: str
    content: str
    category: str = "general"
    tags: List[str] = []
    is_malicious: bool = False
    preferred_llm: Optional[str] = None


class DemoPromptResponse(DemoPromptBase):
    id: int
    usage_count: int
    created_at: datetime
    updated_at: datetime


class DemoPromptCreate(DemoPromptBase):
    pass


class DemoPromptUpdate(DemoPromptBase):
    pass


class DemoPromptSearchRequest(BaseModel):
    query: str
    category: Optional[str] = None
    limit: int = 10


# Playbook schemas — custom POC playbooks managed via the admin UI.
# Built-in playbooks live in backend/playbooks.py and are read-only.
class PlaybookPromptIn(BaseModel):
    """One prompt inside a playbook. `expected` drives the pass/fail scoring."""
    id: str
    category: str = "Custom"
    prompt: str
    expected: str = "blocked"  # "blocked" or "allowed"
    description: Optional[str] = None


class PlaybookCreate(BaseModel):
    name: str
    description: Optional[str] = None
    prompts: List[PlaybookPromptIn] = []


class PlaybookUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    prompts: Optional[List[PlaybookPromptIn]] = None
