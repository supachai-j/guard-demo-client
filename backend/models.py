from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class AppConfig(Base):
    __tablename__ = "app_config"

    id = Column(Integer, primary_key=True, index=True)
    openai_api_key = Column(String, nullable=True)
    lakera_api_key = Column(String, nullable=True)
    lakera_project_id = Column(String, nullable=True)
    business_name = Column(String, nullable=True)
    tagline = Column(String, nullable=True)
    hero_text = Column(String, nullable=True)
    hero_image_url = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    system_prompt = Column(Text, nullable=True)
    openai_model = Column(String, default="gpt-4o-mini")
    temperature = Column(String, default="7")
    lakera_enabled = Column(Boolean, default=True)
    lakera_blocking_mode = Column(Boolean, default=False)
    use_litellm = Column(Boolean, default=False)
    litellm_base_url = Column(String, nullable=True)
    # LiteLLM proxy virtual key (when use_litellm); separate from direct OpenAI key
    litellm_virtual_key = Column(String, nullable=True)
    # Multi-provider LLM support. llm_provider selects which provider's key/base_url is used at call time;
    # values: "openai", "anthropic", "google", "mistral", "groq", "together", "ollama", "litellm_proxy".
    # Keys are stored per provider so switching does not require re-entry.
    llm_provider = Column(String, nullable=True, default="openai")
    anthropic_api_key = Column(String, nullable=True)
    google_api_key = Column(String, nullable=True)
    mistral_api_key = Column(String, nullable=True)
    groq_api_key = Column(String, nullable=True)
    together_api_key = Column(String, nullable=True)
    ollama_base_url = Column(String, nullable=True)
    # Guardrail names selected by app when using LiteLLM-native Lakera guardrails.
    litellm_guardrail_name = Column(String, nullable=True)
    litellm_guardrail_monitor_name = Column(String, nullable=True)
    rag_content_scanning = Column(Boolean, default=False)
    rag_lakera_project_id = Column(String, nullable=True)
    # UI theming
    theme = Column(String, nullable=True, default="blue")
    # Guardrail provider (Lakera / OpenAI Moderation / Bedrock / …)
    guardrail_provider = Column(String, nullable=True, default="lakera")
    # AWS Bedrock Guardrails — requires a guardrail pre-created in the Bedrock console
    bedrock_guardrail_id = Column(String, nullable=True)
    bedrock_guardrail_version = Column(String, nullable=True)
    bedrock_region = Column(String, nullable=True)
    bedrock_access_key_id = Column(String, nullable=True)
    bedrock_secret_access_key = Column(String, nullable=True)
    # Azure AI Content Safety
    azure_content_safety_endpoint = Column(String, nullable=True)
    azure_content_safety_key = Column(String, nullable=True)
    # Palo Alto Prisma AIRS
    palo_alto_api_key = Column(String, nullable=True)
    palo_alto_profile_name = Column(String, nullable=True)
    palo_alto_host = Column(String, nullable=True)
    # Portkey (LLM gateway — used when llm_provider="portkey")
    portkey_api_key = Column(String, nullable=True)
    portkey_virtual_key = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Tool(Base):
    __tablename__ = "tools"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    type = Column(String)  # "mcp" or "http"
    description = Column(Text, nullable=True)
    endpoint = Column(String)
    enabled = Column(Boolean, default=True)
    config_json = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RagSource(Base):
    __tablename__ = "rag_sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    content = Column(Text)
    chunks_count = Column(Integer, default=0)
    source_type = Column(String, default="generated")  # "generated", "uploaded"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MCPToolCapabilities(Base):
    __tablename__ = "mcp_tool_capabilities"

    id = Column(Integer, primary_key=True, index=True)
    tool_id = Column(Integer, index=True)
    tool_name = Column(String, index=True)
    server_name = Column(String)
    session_info = Column(JSON, nullable=True)
    discovery_results = Column(JSON, default={})
    last_discovered = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DemoPrompt(Base):
    __tablename__ = "demo_prompts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    content = Column(Text)
    category = Column(String, default="general")  # "general", "security", "tools", "rag", etc.
    tags = Column(JSON, default=[])  # Array of searchable tags
    is_malicious = Column(Boolean, default=False)  # Flag for security testing prompts
    preferred_llm = Column(String, nullable=True)  # Optional preferred backend model for this prompt
    usage_count = Column(Integer, default=0)  # Track popularity
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
