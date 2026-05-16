import io
import json
import logging
import os
import shutil
import sys
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import audit, audit_stream, lakera, llm_client, rag, webhooks
from . import auth as _auth
from . import costs as cost_module
from .agent import AgentRequest, run_agent
from .database import engine, get_db
from .guardrail_provider import list_providers_for_ui as list_guardrail_providers_for_ui
from .models import (
    AppConfig,
    AuditLog,
    Base,
    Conversation,
    DemoPrompt,
    MCPToolCapabilities,
    Message,
    Playbook,
    RagSource,
    SessionRecording,
    Tool,
)
from .providers import list_providers_for_ui
from .scenarios import SCENARIOS, get_scenario
from .schemas import (
    AppConfigResponse,
    AppConfigUpdate,
    ChatRequest,
    ChatResponse,
    DemoPromptCreate,
    DemoPromptResponse,
    DemoPromptUpdate,
    PlaybookCreate,
    PlaybookUpdate,
    RagGenerateRequest,
    RagGenerateResponse,
    RagSearchResponse,
    ToolCreate,
    ToolResponse,
    ToolUpdate,
)
from .toolhive import (
    discover_mcp_tool_capabilities_sync,
    store_capabilities,
)

# Configure logging to prevent blocking I/O issues
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# Create database tables
Base.metadata.create_all(bind=engine)


def _migrate_app_config_litellm():
    """Add use_litellm and litellm_base_url to app_config if missing (existing DBs)"""
    with engine.connect() as conn:
        r = conn.execute(text("PRAGMA table_info(app_config)"))
        columns = [row[1] for row in r.fetchall()]
        if "use_litellm" not in columns:
            conn.execute(text("ALTER TABLE app_config ADD COLUMN use_litellm BOOLEAN DEFAULT 0"))
            conn.commit()
        if "litellm_base_url" not in columns:
            conn.execute(text("ALTER TABLE app_config ADD COLUMN litellm_base_url VARCHAR"))
            conn.commit()


# Migration: add preferred_llm to demo_prompts if missing (existing DBs)
def _migrate_demo_prompts_preferred_llm():
    with engine.connect() as conn:
        r = conn.execute(text("PRAGMA table_info(demo_prompts)"))
        columns = [row[1] for row in r.fetchall()]
        if "preferred_llm" not in columns:
            conn.execute(text("ALTER TABLE demo_prompts ADD COLUMN preferred_llm VARCHAR"))
            conn.commit()


# Migration: add theme to app_config if missing (for UI theming)
def _migrate_app_config_theme():
    with engine.connect() as conn:
        r = conn.execute(text("PRAGMA table_info(app_config)"))
        columns = [row[1] for row in r.fetchall()]
        if "theme" not in columns:
            conn.execute(text("ALTER TABLE app_config ADD COLUMN theme VARCHAR"))
            # Set a sensible default for existing rows
            conn.execute(text("UPDATE app_config SET theme = 'blue' WHERE theme IS NULL"))
            conn.commit()


_migrate_app_config_litellm()


def _migrate_app_config_litellm_virtual_key():
    """Add litellm_virtual_key; one-time copy from openai_api_key for existing LiteLLM rows that used the old single field."""
    with engine.connect() as conn:
        r = conn.execute(text("PRAGMA table_info(app_config)"))
        columns = [row[1] for row in r.fetchall()]
        if "litellm_virtual_key" not in columns:
            conn.execute(text("ALTER TABLE app_config ADD COLUMN litellm_virtual_key VARCHAR"))
            conn.commit()
            conn.execute(
                text(
                    """
                    UPDATE app_config
                    SET litellm_virtual_key = openai_api_key
                    WHERE use_litellm = 1
                      AND (litellm_virtual_key IS NULL OR litellm_virtual_key = '')
                      AND openai_api_key IS NOT NULL AND openai_api_key != ''
                    """
                )
            )
            conn.commit()


_migrate_demo_prompts_preferred_llm()
_migrate_app_config_theme()
_migrate_app_config_litellm_virtual_key()


def _migrate_app_config_litellm_guardrail_fields():
    """Add LiteLLM guardrail fields for block/monitor naming if missing."""
    with engine.connect() as conn:
        r = conn.execute(text("PRAGMA table_info(app_config)"))
        columns = [row[1] for row in r.fetchall()]
        if "litellm_guardrail_name" not in columns:
            conn.execute(text("ALTER TABLE app_config ADD COLUMN litellm_guardrail_name VARCHAR"))
            conn.commit()
        if "litellm_guardrail_monitor_name" not in columns:
            conn.execute(text("ALTER TABLE app_config ADD COLUMN litellm_guardrail_monitor_name VARCHAR"))
            conn.commit()


_migrate_app_config_litellm_guardrail_fields()


def _migrate_app_config_multi_provider():
    """Add multi-provider columns + backfill llm_provider from legacy use_litellm flag."""
    new_columns = {
        "llm_provider": "VARCHAR",
        "anthropic_api_key": "VARCHAR",
        "google_api_key": "VARCHAR",
        "mistral_api_key": "VARCHAR",
        "groq_api_key": "VARCHAR",
        "together_api_key": "VARCHAR",
        "ollama_base_url": "VARCHAR",
    }
    with engine.connect() as conn:
        r = conn.execute(text("PRAGMA table_info(app_config)"))
        columns = [row[1] for row in r.fetchall()]
        for name, col_type in new_columns.items():
            if name not in columns:
                conn.execute(text(f"ALTER TABLE app_config ADD COLUMN {name} {col_type}"))
                conn.commit()
        # Backfill llm_provider for existing rows: use_litellm=1 → litellm_proxy, else openai
        conn.execute(
            text(
                """
                UPDATE app_config
                SET llm_provider = CASE
                    WHEN use_litellm = 1 THEN 'litellm_proxy'
                    ELSE 'openai'
                END
                WHERE llm_provider IS NULL OR llm_provider = ''
                """
            )
        )
        conn.commit()


_migrate_app_config_multi_provider()


def _migrate_app_config_openrouter():
    """Add openrouter_api_key column for existing DBs."""
    with engine.connect() as conn:
        r = conn.execute(text("PRAGMA table_info(app_config)"))
        columns = [row[1] for row in r.fetchall()]
        if "openrouter_api_key" not in columns:
            conn.execute(text("ALTER TABLE app_config ADD COLUMN openrouter_api_key VARCHAR"))
            conn.commit()


_migrate_app_config_openrouter()


def _migrate_app_config_guardrail_provider():
    """Add multi-guardrail-provider columns + backfill default to 'lakera'."""
    new_columns = {
        "guardrail_provider": "VARCHAR",
        "bedrock_guardrail_id": "VARCHAR",
        "bedrock_guardrail_version": "VARCHAR",
        "bedrock_region": "VARCHAR",
        "bedrock_access_key_id": "VARCHAR",
        "bedrock_secret_access_key": "VARCHAR",
        "azure_content_safety_endpoint": "VARCHAR",
        "azure_content_safety_key": "VARCHAR",
        "palo_alto_api_key": "VARCHAR",
        "palo_alto_profile_name": "VARCHAR",
        "palo_alto_host": "VARCHAR",
        "portkey_api_key": "VARCHAR",
        "portkey_virtual_key": "VARCHAR",
    }
    with engine.connect() as conn:
        r = conn.execute(text("PRAGMA table_info(app_config)"))
        columns = [row[1] for row in r.fetchall()]
        for name, col_type in new_columns.items():
            if name not in columns:
                conn.execute(text(f"ALTER TABLE app_config ADD COLUMN {name} {col_type}"))
                conn.commit()
        # Default existing rows to "lakera" so they keep current behavior.
        conn.execute(
            text(
                """
                UPDATE app_config
                SET guardrail_provider = 'lakera'
                WHERE guardrail_provider IS NULL OR guardrail_provider = ''
                """
            )
        )
        conn.commit()


_migrate_app_config_guardrail_provider()


def _migrate_app_config_portkey_base_url():
    """Add portkey_base_url for self-managed Portkey deployments."""
    with engine.connect() as conn:
        r = conn.execute(text("PRAGMA table_info(app_config)"))
        columns = [row[1] for row in r.fetchall()]
        if "portkey_base_url" not in columns:
            conn.execute(text("ALTER TABLE app_config ADD COLUMN portkey_base_url VARCHAR"))
            conn.commit()


def _migrate_app_config_cloudflare():
    """Add Cloudflare Firewall for AI fields."""
    new_columns = {
        "cloudflare_account_id": "VARCHAR",
        "cloudflare_api_token": "VARCHAR",
        "cloudflare_gateway_id": "VARCHAR",
    }
    with engine.connect() as conn:
        r = conn.execute(text("PRAGMA table_info(app_config)"))
        columns = [row[1] for row in r.fetchall()]
        for name, col_type in new_columns.items():
            if name not in columns:
                conn.execute(text(f"ALTER TABLE app_config ADD COLUMN {name} {col_type}"))
                conn.commit()


_migrate_app_config_portkey_base_url()
_migrate_app_config_cloudflare()


def _migrate_app_config_webhook():
    """Add webhook_url for outbound flag notifications."""
    with engine.connect() as conn:
        r = conn.execute(text("PRAGMA table_info(app_config)"))
        columns = [row[1] for row in r.fetchall()]
        if "webhook_url" not in columns:
            conn.execute(text("ALTER TABLE app_config ADD COLUMN webhook_url VARCHAR"))
            conn.commit()


def _migrate_audit_log_tokens():
    """Add token / cost columns to audit_log."""
    with engine.connect() as conn:
        r = conn.execute(text("PRAGMA table_info(audit_log)"))
        columns = [row[1] for row in r.fetchall()]
        for name, ctype in [("input_tokens", "INTEGER"), ("output_tokens", "INTEGER"), ("cost_usd", "VARCHAR")]:
            if name not in columns:
                conn.execute(text(f"ALTER TABLE audit_log ADD COLUMN {name} {ctype}"))
                conn.commit()


_migrate_app_config_webhook()
_migrate_audit_log_tokens()

app = FastAPI(title="Agentic Demo API", description="Backend API for the Agentic Demo application", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the bundled fake-company brand assets (logos / hero images) used by
# the one-click scenario loader. Mounted at /static/fakecompanies/...
_fakecompanies_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fakecompanies")
if os.path.isdir(_fakecompanies_dir):
    app.mount("/static/fakecompanies", StaticFiles(directory=_fakecompanies_dir), name="fakecompanies")


def _ensure_active_model_valid(config: AppConfig, db: Session) -> None:
    valid_models = llm_client.get_models(config)
    if valid_models and config.openai_model not in valid_models:
        config.openai_model = valid_models[0]
        db.commit()
        db.refresh(config)


@app.get("/")
async def root():
    return {"message": "Agentic Demo API is running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/api/auth/status")
async def get_auth_status():
    """Public — frontend uses this to decide whether to show the login screen."""
    return _auth.auth_status()


@app.post("/api/auth/login", response_model=_auth.LoginResponse)
async def login(body: _auth.LoginRequest):
    """Validate credentials and return a JWT bearer token."""
    result = _auth.authenticate(body.username, body.password)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    token, expires = result
    return _auth.LoginResponse(access_token=token, token_type="bearer", expires_at=expires, user=body.username)


@app.get("/api/auth/me", response_model=_auth.MeResponse)
async def me(user: str = Depends(_auth.require_admin)):
    """Return the current authenticated user. 401 when no/expired token."""
    return _auth.MeResponse(user=user)


@app.post("/api/auth/logout")
async def logout(user: str = Depends(_auth.require_admin)):
    """JWT is stateless — logout is a client-side concern (drop the token).
    Endpoint exists so the UI can confirm the call succeeded."""
    return {"logged_out": True, "user": user}


# Fields that must be hidden from non-admin callers (every credential).
_SECRET_CONFIG_FIELDS = (
    "openai_api_key", "anthropic_api_key", "google_api_key", "mistral_api_key",
    "groq_api_key", "together_api_key", "openrouter_api_key",
    "lakera_api_key", "litellm_virtual_key",
    "bedrock_access_key_id", "bedrock_secret_access_key",
    "azure_content_safety_key",
    "palo_alto_api_key",
    "portkey_api_key", "portkey_virtual_key",
    "cloudflare_api_token",
)


def _config_response(config: AppConfig, *, authenticated: bool) -> AppConfig:
    """Return a config view with secrets blanked for non-admins.

    The Landing page reads /api/config for branding fields; we don't want
    those visitors to see API keys. The AdminConsole sends a Bearer token
    so it gets the unredacted config."""
    if authenticated:
        return config
    # Build a shallow copy that pydantic can serialise; we just blank the
    # secret fields in-place but on a *detached* attribute dict so the DB
    # row isn't mutated.
    from copy import copy as _copy
    safe = _copy(config)
    for field in _SECRET_CONFIG_FIELDS:
        if hasattr(safe, field) and getattr(safe, field, None):
            setattr(safe, field, "***")
    return safe


# App Config endpoints
@app.get("/api/config", response_model=AppConfigResponse)
async def get_config(
    user: Optional[str] = Depends(_auth.current_user),
    db: Session = Depends(get_db),
):
    """Public read; secret fields are masked unless the caller is admin."""
    config = db.query(AppConfig).first()
    if not config:
        config = AppConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    return _config_response(config, authenticated=bool(user))


@app.put("/api/config", response_model=AppConfigResponse, dependencies=[Depends(_auth.require_admin)])
async def update_config(config_update: AppConfigUpdate, db: Session = Depends(get_db)):
    config = db.query(AppConfig).first()
    if not config:
        config = AppConfig()
        db.add(config)

    # Update fields
    for field, value in config_update.dict(exclude_unset=True).items():
        setattr(config, field, value)

    # Keep legacy use_litellm flag in sync with the new provider selector.
    if config.llm_provider == "litellm_proxy":
        config.use_litellm = True
    elif config.llm_provider:
        config.use_litellm = False

    # Auto-pick a valid model for the active provider when the saved one isn't allowed.
    allowed = llm_client.get_models(config)
    if allowed and (not config.openai_model or config.openai_model not in allowed):
        config.openai_model = allowed[0]

    db.commit()
    db.refresh(config)
    return config


# Export sections: which config fields belong to which section (for selective export/import)
EXPORT_SECTIONS = {
    "appearance": ["business_name", "tagline", "hero_text", "hero_image_url", "logo_url", "theme"],
    "llm": [
        "openai_model",
        "temperature",
        "system_prompt",
        "use_litellm",
        "litellm_base_url",
        "litellm_guardrail_name",
        "litellm_guardrail_monitor_name",
    ],
    "security": ["lakera_enabled", "lakera_blocking_mode"],
    "rag_scanning": ["rag_content_scanning"],
    "api_keys": ["openai_api_key", "litellm_virtual_key", "lakera_api_key"],
    "project_ids": ["lakera_project_id", "rag_lakera_project_id"],
}
SAFE_DEFAULT_INCLUDE = ["appearance", "llm", "security", "rag_scanning", "demo_prompts", "tools", "rag"]


@app.get("/api/config/export", dependencies=[Depends(_auth.require_admin)])
async def export_config(include: Optional[str] = None, version: Optional[str] = None, db: Session = Depends(get_db)):
    """Export configuration as a zip file (v2.0 format with metadata.json and section includes).
    Query params: include=appearance,llm,... (comma-separated; omit = safe default); version=2 (UI sends this to request v2 export)."""
    try:
        # Parse include list; empty or missing = safe default
        if include and include.strip():
            included_sections = [s.strip() for s in include.split(",") if s.strip()]
        else:
            included_sections = list(SAFE_DEFAULT_INCLUDE)
        if not included_sections:
            included_sections = list(SAFE_DEFAULT_INCLUDE)

        config = db.query(AppConfig).first()
        config_dict = {}
        if config:
            for section, fields in EXPORT_SECTIONS.items():
                if section not in included_sections:
                    continue
                for field in fields:
                    val = getattr(config, field, None)
                    if hasattr(val, "isoformat"):
                        val = val.isoformat() if val else None
                    config_dict[field] = val
            # Timestamps for reference (not section-gated)
            config_dict["created_at"] = config.created_at.isoformat() if config.created_at else None
            config_dict["updated_at"] = config.updated_at.isoformat() if config.updated_at else None

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr("config.json", json.dumps(config_dict, indent=2))

            if "tools" in included_sections:
                tools = db.query(Tool).all()
                tools_data = []
                for tool in tools:
                    tool_dict = {
                        "id": tool.id,
                        "name": tool.name,
                        "type": tool.type,
                        "description": tool.description,
                        "endpoint": tool.endpoint,
                        "enabled": tool.enabled,
                        "config_json": tool.config_json,
                        "created_at": tool.created_at.isoformat() if tool.created_at else None,
                        "updated_at": tool.updated_at.isoformat() if tool.updated_at else None,
                    }
                    capabilities = db.query(MCPToolCapabilities).filter(MCPToolCapabilities.tool_id == tool.id).first()
                    if capabilities:
                        tool_dict["mcp_capabilities"] = {
                            "id": capabilities.id,
                            "tool_name": capabilities.tool_name,
                            "server_name": capabilities.server_name,
                            "session_info": capabilities.session_info,
                            "discovery_results": capabilities.discovery_results,
                            "last_discovered": capabilities.last_discovered.isoformat()
                            if capabilities.last_discovered
                            else None,
                            "created_at": capabilities.created_at.isoformat() if capabilities.created_at else None,
                            "updated_at": capabilities.updated_at.isoformat() if capabilities.updated_at else None,
                        }
                    tools_data.append(tool_dict)
                zip_file.writestr("tools.json", json.dumps(tools_data, indent=2))

            if "rag" in included_sections:
                rag_sources = db.query(RagSource).all()
                rag_data = []
                for source in rag_sources:
                    rag_dict = {
                        "id": source.id,
                        "name": source.name,
                        "content": source.content,
                        "chunks_count": source.chunks_count,
                        "source_type": source.source_type,
                        "created_at": source.created_at.isoformat() if source.created_at else None,
                        "updated_at": source.updated_at.isoformat() if source.updated_at else None,
                    }
                    rag_data.append(rag_dict)
                zip_file.writestr("rag_sources.json", json.dumps(rag_data, indent=2))
                from .rag import get_chroma_export_path

                chroma_dir = get_chroma_export_path()
                if os.path.exists(chroma_dir):
                    for root, _dirs, files in os.walk(chroma_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, ".")
                            zip_file.write(file_path, arcname)
            else:
                zip_file.writestr("rag_sources.json", "[]")

            if "demo_prompts" in included_sections:
                prompts = db.query(DemoPrompt).all()
                prompts_data = []
                for p in prompts:
                    prompts_data.append(
                        {
                            "title": p.title,
                            "content": p.content,
                            "category": p.category,
                            "tags": p.tags or [],
                            "is_malicious": p.is_malicious,
                            "preferred_llm": getattr(p, "preferred_llm", None),
                        }
                    )
                zip_file.writestr("demo_prompts.json", json.dumps(prompts_data, indent=2))
            else:
                zip_file.writestr("demo_prompts.json", "[]")

            if "tools" not in included_sections:
                zip_file.writestr("tools.json", "[]")

            metadata = {
                "export_timestamp": datetime.utcnow().isoformat(),
                "version": "2.0",
                "description": "Agentic Demo Configuration Export",
                "includes": included_sections,
            }
            zip_file.writestr("metadata.json", json.dumps(metadata, indent=2))

        zip_buffer.seek(0)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"agentic_demo_config_{timestamp}.zip"
        return StreamingResponse(
            io.BytesIO(zip_buffer.getvalue()),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}") from e


@app.post("/api/config/import", dependencies=[Depends(_auth.require_admin)])
async def import_config(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import configuration from a zip file. Supports v1.0 (full replace) and v2.0 (merge by section)."""
    try:
        if not file.filename.endswith(".zip"):
            raise HTTPException(status_code=400, detail="File must be a .zip file")
        file_content = await file.read()
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_zip_path = os.path.join(temp_dir, "import.zip")
            with open(temp_zip_path, "wb") as f:
                f.write(file_content)
            with zipfile.ZipFile(temp_zip_path, "r") as zip_file:
                zip_file.extractall(temp_dir)

            metadata_path = os.path.join(temp_dir, "metadata.json")
            if not os.path.exists(metadata_path):
                raise HTTPException(status_code=400, detail="Missing metadata.json")
            with open(metadata_path, "r") as f:
                metadata = json.load(f)
            version = metadata.get("version", "1.0")
            includes = metadata.get("includes") or []

            if version == "1.0":
                # Legacy: full replace; require all files
                for required in ["config.json", "tools.json", "rag_sources.json"]:
                    if not os.path.exists(os.path.join(temp_dir, required)):
                        raise HTTPException(status_code=400, detail=f"Missing required file: {required}")
                with open(os.path.join(temp_dir, "config.json"), "r") as f:
                    config_data = json.load(f)
                db.query(AppConfig).delete()
                new_config = AppConfig(
                    openai_api_key=config_data.get("openai_api_key"),
                    litellm_virtual_key=config_data.get("litellm_virtual_key"),
                    lakera_api_key=config_data.get("lakera_api_key"),
                    lakera_project_id=config_data.get("lakera_project_id"),
                    rag_lakera_project_id=config_data.get("rag_lakera_project_id"),
                    business_name=config_data.get("business_name"),
                    tagline=config_data.get("tagline"),
                    hero_text=config_data.get("hero_text"),
                    hero_image_url=config_data.get("hero_image_url"),
                    logo_url=config_data.get("logo_url"),
                    system_prompt=config_data.get("system_prompt"),
                    openai_model=config_data.get("openai_model", "gpt-4o-mini"),
                    temperature=config_data.get("temperature", "7"),
                    lakera_enabled=config_data.get("lakera_enabled", True),
                    lakera_blocking_mode=config_data.get("lakera_blocking_mode", False),
                    rag_content_scanning=config_data.get("rag_content_scanning", False),
                    theme=config_data.get("theme"),
                    use_litellm=config_data.get("use_litellm", False),
                    litellm_base_url=config_data.get("litellm_base_url"),
                    litellm_guardrail_name=config_data.get("litellm_guardrail_name"),
                    litellm_guardrail_monitor_name=config_data.get("litellm_guardrail_monitor_name"),
                )
                db.add(new_config)
                db.flush()
                # Legacy v1 exports: key may only be in openai_api_key for LiteLLM
                use_litellm_val = getattr(new_config, "use_litellm", False) or False
                if use_litellm_val and not (getattr(new_config, "litellm_virtual_key", None) or "").strip():
                    if new_config.openai_api_key:
                        new_config.litellm_virtual_key = new_config.openai_api_key
                # Auto-pick model when imported config has LiteLLM or invalid model for OpenAI
                if use_litellm_val and getattr(new_config, "litellm_virtual_key", None):
                    allowed = llm_client.get_models(new_config)
                    if allowed and (not new_config.openai_model or new_config.openai_model not in allowed):
                        new_config.openai_model = allowed[0]
                elif not use_litellm_val and new_config.openai_model not in llm_client.STATIC_MODELS:
                    new_config.openai_model = llm_client.STATIC_MODELS[0]
                with open(os.path.join(temp_dir, "tools.json"), "r") as f:
                    tools_data = json.load(f)
                db.query(MCPToolCapabilities).delete()
                db.query(Tool).delete()
                for tool_data in tools_data:
                    new_tool = Tool(
                        name=tool_data["name"],
                        type=tool_data["type"],
                        description=tool_data.get("description"),
                        endpoint=tool_data["endpoint"],
                        enabled=tool_data.get("enabled", True),
                        config_json=tool_data.get("config_json", {}),
                    )
                    db.add(new_tool)
                    db.flush()
                    if "mcp_capabilities" in tool_data:
                        cap_data = tool_data["mcp_capabilities"]
                        db.add(
                            MCPToolCapabilities(
                                tool_id=new_tool.id,
                                tool_name=cap_data["tool_name"],
                                server_name=cap_data.get("server_name"),
                                session_info=cap_data.get("session_info"),
                                discovery_results=cap_data.get("discovery_results", {}),
                            )
                        )
                with open(os.path.join(temp_dir, "rag_sources.json"), "r") as f:
                    rag_data = json.load(f)
                db.query(RagSource).delete()
                for rag_source_data in rag_data:
                    db.add(
                        RagSource(
                            name=rag_source_data["name"],
                            content=rag_source_data["content"],
                            chunks_count=rag_source_data.get("chunks_count", 0),
                            source_type=rag_source_data.get("source_type", "generated"),
                        )
                    )
                chroma_source_dir = os.path.join(temp_dir, "data", "chroma")
                if os.path.exists(chroma_source_dir):
                    chroma_import_dir = "data/chroma_import"
                    if os.path.exists(chroma_import_dir):
                        shutil.rmtree(chroma_import_dir)
                    shutil.copytree(chroma_source_dir, chroma_import_dir)
                    try:
                        from .rag import reinitialize_chromadb

                        reinitialize_chromadb(chroma_import_dir)
                    except Exception:
                        pass
                # v1.0: import demo_prompts from demo_prompts.json if present, else from data/agentic_demo.db (old export format)
                prompts_path_v1 = os.path.join(temp_dir, "demo_prompts.json")
                db_path_v1 = os.path.join(temp_dir, "data", "agentic_demo.db")
                if os.path.exists(prompts_path_v1):
                    try:
                        with open(prompts_path_v1, "r") as f:
                            prompts_data_v1 = json.load(f)
                        if isinstance(prompts_data_v1, list):
                            db.query(DemoPrompt).delete()
                            for p in prompts_data_v1:
                                if not isinstance(p, dict):
                                    continue
                                title = p.get("title") or ""
                                content = p.get("content") or ""
                                if not title and not content:
                                    continue
                                db.add(
                                    DemoPrompt(
                                        title=title,
                                        content=content,
                                        category=p.get("category", "general"),
                                        tags=p.get("tags") if isinstance(p.get("tags"), list) else [],
                                        is_malicious=p.get("is_malicious", False),
                                        preferred_llm=p.get("preferred_llm"),
                                    )
                                )
                    except Exception:
                        pass
                elif os.path.exists(db_path_v1):
                    try:
                        import sqlite3

                        conn = sqlite3.connect(db_path_v1)
                        conn.row_factory = sqlite3.Row
                        cur = conn.execute("PRAGMA table_info(demo_prompts)")
                        columns = [row[1] for row in cur.fetchall()]
                        conn.close()
                        if "title" in columns and "content" in columns:
                            conn = sqlite3.connect(db_path_v1)
                            conn.row_factory = sqlite3.Row
                            cur = conn.execute(
                                "SELECT title, content, category, tags, is_malicious FROM demo_prompts"
                                + (", preferred_llm" if "preferred_llm" in columns else "")
                            )
                            rows = cur.fetchall()
                            conn.close()
                            db.query(DemoPrompt).delete()
                            for row in rows:
                                r = dict(row)
                                tags = r.get("tags")
                                if isinstance(tags, str):
                                    try:
                                        tags = json.loads(tags) if tags else []
                                    except Exception:
                                        tags = []
                                if not isinstance(tags, list):
                                    tags = []
                                db.add(
                                    DemoPrompt(
                                        title=r.get("title") or "",
                                        content=r.get("content") or "",
                                        category=r.get("category") or "general",
                                        tags=tags,
                                        is_malicious=bool(r.get("is_malicious", False)),
                                        preferred_llm=r.get("preferred_llm") if "preferred_llm" in columns else None,
                                    )
                                )
                    except Exception:
                        pass
                db.commit()
                return {
                    "message": "Configuration imported successfully",
                    "imported_at": datetime.utcnow().isoformat(),
                    "metadata": metadata,
                }

            # Version 2.0: merge by section
            config_path = os.path.join(temp_dir, "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    config_data = json.load(f)
                config_row = db.query(AppConfig).first()
                if not config_row:
                    config_row = AppConfig()
                    db.add(config_row)
                    db.flush()
                for section, fields in EXPORT_SECTIONS.items():
                    if section not in includes:
                        continue
                    for field in fields:
                        if field in config_data:
                            setattr(config_row, field, config_data[field])
                # Older exports may store the LiteLLM key only in openai_api_key
                use_lm = getattr(config_row, "use_litellm", False)
                if use_lm and not (getattr(config_row, "litellm_virtual_key", None) or "").strip():
                    if getattr(config_row, "openai_api_key", None):
                        config_row.litellm_virtual_key = config_row.openai_api_key
                # Auto-pick model (same as PUT /api/config)
                if use_lm and getattr(config_row, "litellm_virtual_key", None):
                    allowed = llm_client.get_models(config_row)
                    if allowed and (not config_row.openai_model or config_row.openai_model not in allowed):
                        config_row.openai_model = allowed[0]
                elif not use_lm and config_row.openai_model not in llm_client.STATIC_MODELS:
                    config_row.openai_model = llm_client.STATIC_MODELS[0]

            if "tools" in includes:
                tools_path = os.path.join(temp_dir, "tools.json")
                if os.path.exists(tools_path):
                    with open(tools_path, "r") as f:
                        tools_data = json.load(f)
                    if isinstance(tools_data, list) and len(tools_data) > 0:
                        db.query(MCPToolCapabilities).delete()
                        db.query(Tool).delete()
                        for tool_data in tools_data:
                            new_tool = Tool(
                                name=tool_data["name"],
                                type=tool_data["type"],
                                description=tool_data.get("description"),
                                endpoint=tool_data["endpoint"],
                                enabled=tool_data.get("enabled", True),
                                config_json=tool_data.get("config_json", {}),
                            )
                            db.add(new_tool)
                            db.flush()
                            if "mcp_capabilities" in tool_data:
                                cap_data = tool_data["mcp_capabilities"]
                                db.add(
                                    MCPToolCapabilities(
                                        tool_id=new_tool.id,
                                        tool_name=cap_data["tool_name"],
                                        server_name=cap_data.get("server_name"),
                                        session_info=cap_data.get("session_info"),
                                        discovery_results=cap_data.get("discovery_results", {}),
                                    )
                                )

            if "rag" in includes:
                rag_path = os.path.join(temp_dir, "rag_sources.json")
                if os.path.exists(rag_path):
                    with open(rag_path, "r") as f:
                        rag_data = json.load(f)
                    if isinstance(rag_data, list):
                        db.query(RagSource).delete()
                        for rag_source_data in rag_data:
                            db.add(
                                RagSource(
                                    name=rag_source_data["name"],
                                    content=rag_source_data["content"],
                                    chunks_count=rag_source_data.get("chunks_count", 0),
                                    source_type=rag_source_data.get("source_type", "generated"),
                                )
                            )
                chroma_source_dir = os.path.join(temp_dir, "data", "chroma")
                if os.path.exists(chroma_source_dir):
                    chroma_import_dir = "data/chroma_import"
                    if os.path.exists(chroma_import_dir):
                        shutil.rmtree(chroma_import_dir)
                    shutil.copytree(chroma_source_dir, chroma_import_dir)
                    try:
                        from .rag import reinitialize_chromadb

                        reinitialize_chromadb(chroma_import_dir)
                    except Exception:
                        pass

            if "demo_prompts" in includes:
                prompts_path = os.path.join(temp_dir, "demo_prompts.json")
                if os.path.exists(prompts_path):
                    with open(prompts_path, "r") as f:
                        prompts_data = json.load(f)
                    if isinstance(prompts_data, list):
                        db.query(DemoPrompt).delete()
                        for p in prompts_data:
                            if not isinstance(p, dict):
                                continue
                            title = p.get("title") or ""
                            content = p.get("content") or ""
                            if not title and not content:
                                continue
                            db.add(
                                DemoPrompt(
                                    title=title,
                                    content=content,
                                    category=p.get("category", "general"),
                                    tags=p.get("tags") if isinstance(p.get("tags"), list) else [],
                                    is_malicious=p.get("is_malicious", False),
                                    preferred_llm=p.get("preferred_llm"),
                                )
                            )

            db.commit()
            return {
                "message": "Configuration imported successfully",
                "imported_at": datetime.utcnow().isoformat(),
                "metadata": metadata,
            }
    except zipfile.BadZipFile as e:
        raise HTTPException(status_code=400, detail="Invalid zip file") from e
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in configuration file: {str(e)}") from e
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}") from e


# Chat endpoints
@app.post("/api/chat", response_model=ChatResponse)
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

    _ensure_active_model_valid(config, db)

    # Create agent request
    agent_request = AgentRequest(
        message=request.message,
        session_id=request.session_id,
        conversation_id=request.conversation_id,
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


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest, db: Session = Depends(get_db)):
    """SSE streaming chat. Pre-guardrail runs before tokens; if blocked, emits
    a single 'blocked' event and closes. Otherwise streams 'chunk' events,
    then a final 'done' event with lakera+conversation_id+tool_traces."""
    import asyncio
    import time as _time

    from .agent import _ensure_conversation, _load_conversation_history
    from .guardrail_provider import active_provider_id as _active_gid
    from .guardrail_provider import resolve_provider as _resolve_provider
    from .providers import provider_id as _llm_pid

    config = db.query(AppConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration found")
    _ensure_active_model_valid(config, db)

    async def event_stream():
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
        messages: List[Dict[str, Any]] = []
        if config.system_prompt:
            messages.append({"role": "system", "content": config.system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": request.message})

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


class _ConfigOverride:
    """Read-through wrapper around AppConfig that overrides selected fields
    without touching the underlying SQLAlchemy row. Used by /api/chat/compare
    so we can run the agent twice with different `lakera_enabled` values
    without persisting either change."""

    def __init__(self, base, **overrides):
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_overrides", overrides)

    def __getattr__(self, name):
        overrides = object.__getattribute__(self, "_overrides")
        if name in overrides:
            return overrides[name]
        return getattr(object.__getattribute__(self, "_base"), name)


@app.post("/api/chat/compare")
async def chat_compare(request: ChatRequest, db: Session = Depends(get_db)):
    """Run the same prompt twice — once with the active guardrail on, once
    off — and return both results side-by-side. Works for every guardrail
    provider (Lakera / OpenAI Moderation / Bedrock / Azure / Palo Alto AIRS
    / Cloudflare Firewall for AI); the active one is whatever is selected
    in Admin → Security. The response includes the provider id + display
    name so the UI can label panes correctly."""
    from .guardrail_provider import GUARDRAIL_PROVIDERS, active_provider_id, resolve_provider

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

    _ensure_active_model_valid(config, db)
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


# RAG endpoints
@app.post("/api/rag/generate", response_model=RagGenerateResponse, dependencies=[Depends(_auth.require_admin)])
async def generate_rag_content(request: RagGenerateRequest, db: Session = Depends(get_db)):
    try:
        # Generate content
        markdown = await rag.generate_seed_pack(
            industry=request.industry,
            seed_prompt=request.seed_prompt,
            options={},  # Will be expanded in guided mode
            mode="quick",
        )

        # If not preview only, ingest the content
        if not request.preview_only:
            source_meta = {
                "name": f"Generated Content - {request.industry}",
                "industry": request.industry,
                "seed_prompt": request.seed_prompt,
                "source_type": "generated",
            }
            await rag.ingest_markdown(markdown, source_meta, db)
            return RagGenerateResponse(markdown=markdown, ingested=True)
        else:
            return RagGenerateResponse(markdown=markdown, ingested=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate content: {str(e)}") from e


@app.get("/api/rag/search", response_model=RagSearchResponse)
async def search_rag_content(query: str, db: Session = Depends(get_db)):
    try:
        results = await rag.retrieve(query, top_k=5)
        return RagSearchResponse(chunks=results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search: {str(e)}") from e


@app.get("/api/rag/sources")
async def get_rag_sources(db: Session = Depends(get_db)):
    """Get all RAG sources"""
    try:
        sources = db.query(RagSource).order_by(RagSource.created_at.desc()).all()
        return {
            "sources": [
                {
                    "id": source.id,
                    "name": source.name,
                    "source_type": source.source_type,
                    "chunks_count": source.chunks_count,
                    "created_at": source.created_at.isoformat() if source.created_at else None,
                    "updated_at": source.updated_at.isoformat() if source.updated_at else None,
                }
                for source in sources
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get RAG sources: {str(e)}") from e


@app.delete("/api/rag/clear", dependencies=[Depends(_auth.require_admin)])
async def clear_rag_content(db: Session = Depends(get_db)):
    """Clear all RAG content"""
    try:
        # Clear ChromaDB collection - get all IDs first, then delete them
        try:
            # Get all documents to get their IDs
            all_docs = rag.collection.get()
            if all_docs and all_docs.get("ids"):
                rag.collection.delete(ids=all_docs["ids"])
        except Exception as chroma_error:
            print(f"ChromaDB clear error: {chroma_error}")
            # If ChromaDB fails, continue with database cleanup

        # Clear database sources
        db.query(RagSource).delete()
        db.commit()

        # Clear uploaded files from uploads directory
        uploads_dir = "uploads"
        if os.path.exists(uploads_dir):
            try:
                for filename in os.listdir(uploads_dir):
                    file_path = os.path.join(uploads_dir, filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        print(f"Deleted uploaded file: {filename}")
            except Exception as file_error:
                print(f"Error deleting uploaded files: {file_error}")
                # Continue even if file deletion fails

        return {"message": "RAG content and uploaded files cleared successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear RAG content: {str(e)}") from e


@app.post("/api/rag/upload", dependencies=[Depends(_auth.require_admin)])
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload and ingest a file into the RAG system"""
    try:
        # Validate file type
        allowed_types = {
            "application/pdf": ".pdf",
            "text/markdown": ".md",
            "text/plain": ".txt",
            "text/csv": ".csv",
            "application/octet-stream": ".csv",  # Allow CSV files detected as octet-stream
        }

        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"File type {file.content_type} not supported. Allowed: {list(allowed_types.keys())}",
            )

        # Validate file size (10MB limit)
        if file.size > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File size exceeds 10MB limit")

        # Create uploads directory if it doesn't exist
        upload_dir = "uploads"
        os.makedirs(upload_dir, exist_ok=True)

        # Save file
        file_path = os.path.join(upload_dir, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Ingest file into RAG
        source_meta = {
            "name": file.filename,
            "source_type": "uploaded",
            "file_path": file_path,
            "mimetype": file.content_type,
        }

        result = await rag.ingest_file(file_path, file.content_type, source_meta, db)

        return {"message": "File uploaded and ingested successfully", "filename": file.filename, "result": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}") from e


@app.post("/api/rag/test-ingest")
async def test_ingest():
    """Test endpoint to ingest sample content"""
    try:
        with open("test_content.md", "r") as f:
            markdown = f.read()

        source_meta = {
            "name": "Digital Banking Guide",
            "industry": "FinTech",
            "source_type": "uploaded",
            "file_path": "test_content.md",
        }

        result = await rag.ingest_markdown(markdown, source_meta)
        return {"message": "Test content ingested", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to ingest test content: {str(e)}") from e


# Tool endpoints
@app.get("/api/tools", response_model=List[ToolResponse])
async def get_tools(db: Session = Depends(get_db)):
    tools = db.query(Tool).all()
    return tools


@app.post("/api/tools", response_model=ToolResponse, dependencies=[Depends(_auth.require_admin)])
async def create_tool(tool: ToolCreate, db: Session = Depends(get_db)):
    db_tool = Tool(**tool.dict())
    db.add(db_tool)
    db.commit()
    db.refresh(db_tool)
    return db_tool


@app.put("/api/tools/{tool_id}", response_model=ToolResponse, dependencies=[Depends(_auth.require_admin)])
async def update_tool(tool_id: int, tool: ToolUpdate, db: Session = Depends(get_db)):
    db_tool = db.query(Tool).filter(Tool.id == tool_id).first()
    if not db_tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    for field, value in tool.dict(exclude_unset=True).items():
        setattr(db_tool, field, value)

    db.commit()
    db.refresh(db_tool)
    return db_tool


@app.delete("/api/tools/{tool_id}", dependencies=[Depends(_auth.require_admin)])
async def delete_tool(tool_id: int, db: Session = Depends(get_db)):
    db_tool = db.query(Tool).filter(Tool.id == tool_id).first()
    if not db_tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    db.delete(db_tool)
    db.commit()
    return {"message": "Tool deleted"}


@app.post("/api/tools/test/{tool_id}", dependencies=[Depends(_auth.require_admin)])
async def test_tool(tool_id: int, db: Session = Depends(get_db)):
    """Test a tool's connectivity and basic functionality"""
    tool = db.query(Tool).filter(Tool.id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    # Get configuration for Lakera parameters
    config = db.query(AppConfig).first()
    lakera_api_key = config.lakera_api_key if config and config.lakera_enabled else None
    lakera_project_id = config.lakera_project_id if config else None
    lakera_blocking_mode = config.lakera_blocking_mode if config and config.lakera_enabled else True

    if tool.type in ["mcp", "http"]:
        # For MCP tools, try to discover capabilities
        try:
            discovery_result = await discover_mcp_tool_capabilities_sync(
                {"name": tool.name, "endpoint": tool.endpoint},
                lakera_api_key=lakera_api_key,
                lakera_project_id=lakera_project_id,
                lakera_blocking_mode=lakera_blocking_mode,
            )
            # Store the discovered capabilities
            await store_capabilities(tool.id, tool.name, discovery_result, db)
            return {
                "status": "success",
                "message": f"MCP tool {tool.name} discovery completed",
                "discovery": discovery_result,
            }
        except Exception as e:
            return {"status": "error", "message": f"MCP tool discovery failed: {str(e)}"}
    else:
        # For HTTP tools, test basic connectivity
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Try HEAD first, then GET if HEAD fails
                try:
                    response = await client.head(tool.endpoint)
                    if response.status_code < 400:
                        return {"status": "success", "message": f"HTTP tool {tool.name} is reachable"}
                except Exception:
                    pass

                # Try GET as fallback
                response = await client.get(tool.endpoint, timeout=10.0)
                if response.status_code < 400:
                    return {"status": "success", "message": f"HTTP tool {tool.name} is reachable"}
                else:
                    return {"status": "error", "message": f"HTTP tool returned status {response.status_code}"}
        except Exception as e:
            return {"status": "error", "message": f"HTTP tool test failed: {str(e)}"}


@app.get("/api/tools/{tool_id}/capabilities")
async def get_tool_capabilities(tool_id: int, db: Session = Depends(get_db)):
    """Get stored capabilities for an MCP tool"""
    from .toolhive import get_stored_capabilities

    tool = db.query(Tool).filter(Tool.id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    if tool.type != "mcp":
        raise HTTPException(status_code=400, detail="Only MCP tools have capabilities")

    capabilities = await get_stored_capabilities(tool_id, db)
    if capabilities:
        return {"tool_id": tool_id, "tool_name": tool.name, "capabilities": capabilities}
    else:
        return {
            "tool_id": tool_id,
            "tool_name": tool.name,
            "capabilities": None,
            "message": "No capabilities discovered yet. Run the test endpoint first.",
        }


# Export/Import endpoints (legacy)
@app.get("/api/export")
async def legacy_export_config(db: Session = Depends(get_db)):
    config = db.query(AppConfig).first()
    tools = db.query(Tool).all()
    rag_sources = db.query(RagSource).all()

    return {"config": config, "tools": tools, "rag_sources": rag_sources}


@app.post("/api/import")
async def legacy_import_config(data: dict, db: Session = Depends(get_db)):
    # Placeholder for import functionality
    return {"message": "Import functionality needs to be implemented"}


# Demo Prompt endpoints
@app.get("/api/demo-prompts", response_model=List[DemoPromptResponse])
async def get_demo_prompts(category: Optional[str] = None, limit: int = 50, db: Session = Depends(get_db)):
    """Get all demo prompts, optionally filtered by category"""
    query = db.query(DemoPrompt)

    if category:
        query = query.filter(DemoPrompt.category == category)

    prompts = query.order_by(DemoPrompt.usage_count.desc(), DemoPrompt.created_at.desc()).limit(limit).all()
    return prompts


@app.get("/api/demo-prompts/search")
async def search_demo_prompts(q: str, category: Optional[str] = None, limit: int = 10, db: Session = Depends(get_db)):
    """Search demo prompts by title, content, or tags"""
    if not q or len(q.strip()) < 2:
        return {"prompts": [], "suggestions": []}

    query = q.strip().lower()

    # Search in title, content, and tags
    prompts = db.query(DemoPrompt).filter(
        (DemoPrompt.title.ilike(f"%{query}%"))
        | (DemoPrompt.content.ilike(f"%{query}%"))
        | (DemoPrompt.tags.contains([query]))
    )

    if category:
        prompts = prompts.filter(DemoPrompt.category == category)

    results = prompts.order_by(DemoPrompt.usage_count.desc()).limit(limit).all()

    # Generate suggestions for autocomplete
    suggestions = []
    for prompt in results:
        # Find the best matching part for autocomplete
        title_lower = prompt.title.lower()
        content_lower = prompt.content.lower()

        if query in title_lower:
            # Use title for autocomplete
            start_idx = title_lower.find(query)
            suggestion = prompt.title[start_idx : start_idx + len(query) + 20]  # Show more context
            suggestions.append(
                {
                    "text": suggestion,
                    "full_content": prompt.content,
                    "title": prompt.title,
                    "category": prompt.category,
                    "is_malicious": prompt.is_malicious,
                    "prompt_id": prompt.id,
                    "preferred_llm": getattr(prompt, "preferred_llm", None),
                }
            )
        elif query in content_lower:
            # Use content for autocomplete
            start_idx = content_lower.find(query)
            suggestion = prompt.content[start_idx : start_idx + len(query) + 20]
            suggestions.append(
                {
                    "text": suggestion,
                    "full_content": prompt.content,
                    "title": prompt.title,
                    "category": prompt.category,
                    "is_malicious": prompt.is_malicious,
                    "prompt_id": prompt.id,
                    "preferred_llm": getattr(prompt, "preferred_llm", None),
                }
            )

    return {
        "prompts": [
            {
                "id": prompt.id,
                "title": prompt.title,
                "content": prompt.content,
                "category": prompt.category,
                "tags": prompt.tags,
                "is_malicious": prompt.is_malicious,
                "usage_count": prompt.usage_count,
                "preferred_llm": getattr(prompt, "preferred_llm", None),
            }
            for prompt in results
        ],
        "suggestions": suggestions[:5],  # Limit to top 5 suggestions
    }


@app.post("/api/demo-prompts", response_model=DemoPromptResponse, dependencies=[Depends(_auth.require_admin)])
async def create_demo_prompt(prompt: DemoPromptCreate, db: Session = Depends(get_db)):
    """Create a new demo prompt"""
    db_prompt = DemoPrompt(**prompt.dict())
    db.add(db_prompt)
    db.commit()
    db.refresh(db_prompt)
    return db_prompt


@app.put("/api/demo-prompts/{prompt_id}", response_model=DemoPromptResponse, dependencies=[Depends(_auth.require_admin)])
async def update_demo_prompt(prompt_id: int, prompt: DemoPromptUpdate, db: Session = Depends(get_db)):
    """Update an existing demo prompt"""
    db_prompt = db.query(DemoPrompt).filter(DemoPrompt.id == prompt_id).first()
    if not db_prompt:
        raise HTTPException(status_code=404, detail="Demo prompt not found")

    for field, value in prompt.dict(exclude_unset=True).items():
        setattr(db_prompt, field, value)

    db.commit()
    db.refresh(db_prompt)
    return db_prompt


@app.delete("/api/demo-prompts/{prompt_id}", dependencies=[Depends(_auth.require_admin)])
async def delete_demo_prompt(prompt_id: int, db: Session = Depends(get_db)):
    """Delete a demo prompt"""
    db_prompt = db.query(DemoPrompt).filter(DemoPrompt.id == prompt_id).first()
    if not db_prompt:
        raise HTTPException(status_code=404, detail="Demo prompt not found")

    db.delete(db_prompt)
    db.commit()
    return {"message": "Demo prompt deleted"}


@app.post("/api/demo-prompts/{prompt_id}/use")
async def use_demo_prompt(prompt_id: int, db: Session = Depends(get_db)):
    """Increment usage count for a demo prompt"""
    db_prompt = db.query(DemoPrompt).filter(DemoPrompt.id == prompt_id).first()
    if not db_prompt:
        raise HTTPException(status_code=404, detail="Demo prompt not found")

    db_prompt.usage_count += 1
    db.commit()
    return {"message": "Usage count updated", "usage_count": db_prompt.usage_count}


# Lakera endpoints
@app.get("/api/lakera/last")
async def get_last_lakera_result():
    """Get the last Lakera result for frontend polling"""
    result = lakera.get_last_result()
    if result is None:
        raise HTTPException(status_code=404, detail="No Lakera result available")
    return result


@app.get("/api/lakera/last_request")
async def get_last_lakera_request():
    """Get the last Lakera request payload for debugging (messages + metadata)"""
    req = lakera.get_last_request()
    if req is None:
        raise HTTPException(status_code=404, detail="No Lakera request recorded yet")
    return req


@app.get("/api/rag/scanning/last")
async def get_last_rag_scanning_result():
    """Get the last RAG content scanning result"""
    result = rag.get_last_rag_scanning_result()
    if result is None:
        raise HTTPException(status_code=404, detail="No RAG scanning result available")
    return result


@app.get("/api/rag/scanning/progress")
async def get_rag_scanning_progress():
    """Get the current RAG scanning progress"""
    progress = rag.get_rag_scanning_progress()
    if progress is None:
        raise HTTPException(status_code=404, detail="No RAG scanning in progress")
    return progress


@app.get("/api/models")
async def get_available_models(db: Session = Depends(get_db)):
    """Models available for the active provider (dynamic for proxy/Ollama, else static)."""
    config = db.query(AppConfig).first()
    try:
        models = llm_client.get_models(config)
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get models: {str(e)}") from e


@app.get("/api/providers")
async def get_providers():
    """Catalog of supported LLM providers for the Admin Console dropdown."""
    return {"providers": list_providers_for_ui()}


@app.get("/api/guardrail-providers")
async def get_guardrail_providers():
    """Catalog of supported guardrail providers (Lakera, OpenAI Moderation,
    Bedrock Guardrails, …) plus the per-provider AppConfig fields each one
    needs."""
    return {"providers": list_guardrail_providers_for_ui()}


# Demo recorder endpoints — capture sequences of prompts for replay
@app.get("/api/recordings", dependencies=[Depends(_auth.require_admin)])
async def list_recordings(db: Session = Depends(get_db)):
    rows = db.query(SessionRecording).order_by(SessionRecording.created_at.desc()).all()
    return {
        "recordings": [
            {
                "id": r.id,
                "name": r.name,
                "notes": r.notes,
                "event_count": len(r.events or []),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@app.post("/api/recordings", dependencies=[Depends(_auth.require_admin)])
async def create_recording(payload: dict, db: Session = Depends(get_db)):
    """Save a captured session. Body: { name, notes?, events: [{ts,prompt,response,...}] }"""
    name = (payload or {}).get("name") or f"Recording {datetime.utcnow().isoformat(timespec='seconds')}"
    events = (payload or {}).get("events") or []
    if not isinstance(events, list):
        raise HTTPException(status_code=400, detail="events must be a list")
    rec = SessionRecording(
        name=name[:200],
        notes=(payload or {}).get("notes"),
        events=events,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"id": rec.id, "name": rec.name, "event_count": len(events)}


@app.get("/api/recordings/{recording_id}", dependencies=[Depends(_auth.require_admin)])
async def get_recording(recording_id: int, db: Session = Depends(get_db)):
    rec = db.query(SessionRecording).filter(SessionRecording.id == recording_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    return {
        "id": rec.id,
        "name": rec.name,
        "notes": rec.notes,
        "events": rec.events or [],
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


@app.delete("/api/recordings/{recording_id}", dependencies=[Depends(_auth.require_admin)])
async def delete_recording(recording_id: int, db: Session = Depends(get_db)):
    rec = db.query(SessionRecording).filter(SessionRecording.id == recording_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    db.delete(rec)
    db.commit()
    return {"deleted": recording_id}


@app.post("/api/recordings/{recording_id}/replay", dependencies=[Depends(_auth.require_admin)])
async def replay_recording(recording_id: int, db: Session = Depends(get_db)):
    """Re-run every captured prompt through the current agent stack.

    Each event in the recording must have a `prompt` field; the response is
    captured along with the guardrail verdict so the caller can diff against
    the original recording.
    """
    rec = db.query(SessionRecording).filter(SessionRecording.id == recording_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    config = db.query(AppConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration found")
    _ensure_active_model_valid(config, db)

    results: List[dict] = []
    for event in rec.events or []:
        prompt = (event or {}).get("prompt") if isinstance(event, dict) else None
        if not prompt:
            continue
        req = AgentRequest(message=prompt, session_id=f"replay-{recording_id}")
        result = await run_agent(req, config, db, persist=False)
        results.append(
            {
                "prompt": prompt,
                "original": event.get("response") if isinstance(event, dict) else None,
                "replay_response": result.response,
                "lakera": result.lakera_status,
                "tool_traces": result.tool_traces,
                "citations": result.citations,
            }
        )
    return {"recording_id": recording_id, "name": rec.name, "results": results}


# Playbook endpoints — predefined attack suites (OWASP LLM Top 10 etc.)
from . import playbooks as _playbooks  # noqa: E402 — kept here to colocate with route handlers


def _slugify(name: str) -> str:
    """Convert a human name into a URL-safe playbook slug."""
    import re
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return slug or "playbook"


def _unique_slug(db: Session, name: str) -> str:
    """Generate a slug unique across both built-ins and the DB."""
    base = _slugify(name)
    candidate = base
    suffix = 2
    while _playbooks.is_builtin(candidate) or db.query(Playbook).filter(Playbook.slug == candidate).first():
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def _custom_playbook_to_dict(pb: Playbook) -> Dict:
    return {
        "id": pb.slug,
        "name": pb.name,
        "description": pb.description,
        "docs_url": None,
        "prompts": pb.prompts or [],
        "is_builtin": False,
        "created_at": pb.created_at.isoformat() if pb.created_at else None,
        "updated_at": pb.updated_at.isoformat() if pb.updated_at else None,
    }


def _resolve_playbook(db: Session, playbook_id: str) -> Optional[Dict]:
    """Find a playbook by id — built-in first, then DB by slug."""
    pb = _playbooks.get_playbook(playbook_id)
    if pb:
        return {**pb, "is_builtin": True}
    row = db.query(Playbook).filter(Playbook.slug == playbook_id).first()
    if row:
        return _custom_playbook_to_dict(row)
    return None


@app.get("/api/playbooks")
async def list_playbooks(db: Session = Depends(get_db)):
    """Catalog of playbooks — built-ins from code plus customer-specific
    playbooks stored in the `playbooks` table. The is_builtin flag tells
    the UI whether to expose edit/delete controls."""
    builtin = _playbooks.list_playbooks()
    custom_rows = db.query(Playbook).order_by(Playbook.updated_at.desc()).all()
    custom = [
        {
            "id": pb.slug,
            "name": pb.name,
            "docs_url": None,
            "count": len(pb.prompts or []),
            "is_builtin": False,
        }
        for pb in custom_rows
    ]
    return {"playbooks": builtin + custom}


@app.get("/api/playbooks/{playbook_id}")
async def get_playbook(playbook_id: str, db: Session = Depends(get_db)):
    pb = _resolve_playbook(db, playbook_id)
    if not pb:
        raise HTTPException(status_code=404, detail=f"Playbook '{playbook_id}' not found")
    return pb


@app.post("/api/playbooks", dependencies=[Depends(_auth.require_admin)])
async def create_playbook(payload: PlaybookCreate, db: Session = Depends(get_db)):
    """Create a custom (DB-backed) playbook. Slug derives from name and
    is made unique against both built-ins and existing custom rows."""
    if not (payload.name or "").strip():
        raise HTTPException(status_code=400, detail="name is required")
    slug = _unique_slug(db, payload.name)
    row = Playbook(
        slug=slug,
        name=payload.name.strip(),
        description=(payload.description or None),
        prompts=[p.model_dump() for p in payload.prompts],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _custom_playbook_to_dict(row)


@app.put("/api/playbooks/{playbook_id}", dependencies=[Depends(_auth.require_admin)])
async def update_playbook(playbook_id: str, payload: PlaybookUpdate, db: Session = Depends(get_db)):
    """Update a custom playbook. Built-ins are read-only — they return 404
    so the UI never offers an edit button."""
    if _playbooks.is_builtin(playbook_id):
        raise HTTPException(
            status_code=403,
            detail=f"Playbook '{playbook_id}' is built-in and cannot be edited. Duplicate it as a custom playbook first.",
        )
    row = db.query(Playbook).filter(Playbook.slug == playbook_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Playbook '{playbook_id}' not found")
    if payload.name is not None:
        row.name = payload.name.strip()
    if payload.description is not None:
        row.description = payload.description or None
    if payload.prompts is not None:
        row.prompts = [p.model_dump() for p in payload.prompts]
    db.commit()
    db.refresh(row)
    return _custom_playbook_to_dict(row)


@app.delete("/api/playbooks/{playbook_id}", dependencies=[Depends(_auth.require_admin)])
async def delete_playbook(playbook_id: str, db: Session = Depends(get_db)):
    if _playbooks.is_builtin(playbook_id):
        raise HTTPException(
            status_code=403,
            detail=f"Playbook '{playbook_id}' is built-in and cannot be deleted.",
        )
    row = db.query(Playbook).filter(Playbook.slug == playbook_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Playbook '{playbook_id}' not found")
    db.delete(row)
    db.commit()
    return {"deleted": 1}


@app.post("/api/playbooks/{playbook_id}/run", dependencies=[Depends(_auth.require_admin)])
async def run_playbook(playbook_id: str, db: Session = Depends(get_db)):
    """Run every prompt in a playbook through the active guardrail provider.

    Returns a per-prompt verdict + an aggregate detection rate so customers
    can take a screenshot of their "OWASP Top 10 coverage" for the demo
    write-up. Does NOT call the LLM — guardrail-only, fast (< 30s typically).
    """
    import asyncio as _aio

    from .guardrail_provider import GUARDRAIL_PROVIDERS, active_provider_id

    pb = _resolve_playbook(db, playbook_id)
    if not pb:
        raise HTTPException(status_code=404, detail=f"Playbook '{playbook_id}' not found")

    config = db.query(AppConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration found")
    pid = active_provider_id(config)
    provider = GUARDRAIL_PROVIDERS.get(pid)
    if not provider or not provider.is_configured(config):
        raise HTTPException(
            status_code=400,
            detail=f"Active guardrail provider '{pid}' is not configured. Set keys in Admin → Security.",
        )

    def _verdict(flagged: bool, expected: str | None) -> bool:
        """Did the guardrail behave as the playbook prompt declared?

        expected="blocked" → must be flagged
        expected="allowed" → must NOT be flagged
        expected=None      → fall back to the legacy assumption (every prompt
                             is an attack), so flagged means pass."""
        if expected == "allowed":
            return not flagged
        # Treat both "blocked" and a missing expected as "should be flagged".
        return flagged

    async def _scan(item):
        try:
            status = await provider.check_interaction(
                messages=[{"role": "user", "content": item["prompt"]}],
                cfg=config,
                meta=None,
                system_prompt=config.system_prompt,
            )
            flagged = bool(status and status.get("flagged"))
            return {
                "id": item["id"],
                "category": item["category"],
                "prompt": item["prompt"],
                "expected": item.get("expected"),
                "flagged": flagged,
                "passed": _verdict(flagged, item.get("expected")),
                "breakdown": (status or {}).get("breakdown") or [],
                "status": status,
            }
        except Exception as e:
            return {
                "id": item["id"],
                "category": item["category"],
                "prompt": item["prompt"],
                "expected": item.get("expected"),
                "flagged": False,
                # Errors count as failures so the operator notices them in
                # the dashboard instead of silently 100%-passing.
                "passed": False,
                "error": str(e),
            }

    results = await _aio.gather(*[_scan(p) for p in pb["prompts"]])
    detected = sum(1 for r in results if r.get("flagged"))
    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    return {
        "playbook_id": playbook_id,
        "playbook_name": pb["name"],
        "guardrail_provider": pid,
        "guardrail_display_name": provider.display_name,
        "detection_rate": round(100.0 * detected / total, 1) if total else 0.0,
        "pass_rate": round(100.0 * passed / total, 1) if total else 0.0,
        "passed": passed,
        "detected": detected,
        "total": total,
        "results": results,
    }


# Webhook test
@app.post("/api/webhook/test", dependencies=[Depends(_auth.require_admin)])
async def test_webhook(payload: dict, db: Session = Depends(get_db)):
    """Send a synthetic 'guardrail.test' event to the saved webhook_url so the
    admin can verify the integration before relying on it."""
    config = db.query(AppConfig).first()
    url = (payload or {}).get("url") or (config and config.webhook_url) or ""
    if not url.strip():
        raise HTTPException(status_code=400, detail="webhook_url is empty")
    result = await webhooks.fire_test_event(url.strip())
    return result


# Audit cost summary — for the Threat Lab Cost panel
@app.get("/api/audit/cost-summary", dependencies=[Depends(_auth.require_admin)])
async def audit_cost_summary(db: Session = Depends(get_db)):
    """Aggregate audit_log into per-provider cost/tokens for the Cost panel."""
    rows = audit.list_entries(db, limit=1000)
    by_provider: Dict[str, Dict[str, float]] = {}
    total_cost = 0.0
    total_in = 0
    total_out = 0
    for r in rows:
        prov = r.get("llm_provider") or "—"
        bucket = by_provider.setdefault(prov, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        bucket["calls"] += 1
        bucket["input_tokens"] += r.get("input_tokens") or 0
        bucket["output_tokens"] += r.get("output_tokens") or 0
        cost = r.get("cost_usd") or 0.0
        bucket["cost_usd"] += cost
        total_cost += cost
        total_in += r.get("input_tokens") or 0
        total_out += r.get("output_tokens") or 0
    return {
        "total_cost_usd": round(total_cost, 6),
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "by_provider": [{"provider": k, **{kk: (round(vv, 6) if isinstance(vv, float) else vv) for kk, vv in v.items()}}
                        for k, v in by_provider.items()],
    }


# PDF audit report — render audit log summary as a printable PDF
@app.get("/api/audit/report.pdf", dependencies=[Depends(_auth.require_admin)])
async def audit_report_pdf(limit: int = 200, db: Session = Depends(get_db)):
    """Render the last N audit entries as a 1-2 page PDF summary."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    entries = audit.list_entries(db, limit=min(max(limit, 1), 500))
    total = len(entries)
    flagged = sum(1 for e in entries if e.get("guardrail_flagged"))
    blocked = sum(1 for e in entries if e.get("blocked"))
    total_cost = sum((e.get("cost_usd") or 0.0) for e in entries)
    by_provider: Dict[str, int] = {}
    for e in entries:
        by_provider[e.get("guardrail_provider") or "—"] = by_provider.get(e.get("guardrail_provider") or "—", 0) + 1

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                             topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Title"], spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], spaceBefore=12, spaceAfter=4)
    body = styles["BodyText"]

    story = []
    story.append(Paragraph("guard-demo-client — Audit Summary", title_style))
    story.append(Paragraph(f"Generated {datetime.utcnow().isoformat(timespec='seconds')}Z · last {total} entries", body))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Summary", h2))
    summary_data = [
        ["Total entries", str(total)],
        ["Flagged by guardrail", f"{flagged} ({100*flagged/total:.0f}%)" if total else "0"],
        ["Blocked (blocking mode)", str(blocked)],
        ["Total estimated cost (USD)", f"${total_cost:.4f}"],
    ]
    summary_tbl = Table(summary_data, colWidths=[6 * cm, 8 * cm])
    summary_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(summary_tbl)

    story.append(Paragraph("Entries by guardrail provider", h2))
    rows = [["Provider", "Count"]] + [[k, str(v)] for k, v in by_provider.items()]
    prov_tbl = Table(rows, colWidths=[10 * cm, 4 * cm])
    prov_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(prov_tbl)

    story.append(Paragraph("Latest flagged events (max 20)", h2))
    flagged_entries = [e for e in entries if e.get("guardrail_flagged")][:20]
    if flagged_entries:
        head = ["When", "Provider", "Prompt (truncated)"]
        rows = [head]
        for e in flagged_entries:
            when = (e.get("created_at") or "")[:19].replace("T", " ")
            prompt_ = (e.get("user_message") or "")[:80]
            rows.append([when, e.get("guardrail_provider") or "", prompt_])
        flag_tbl = Table(rows, colWidths=[4 * cm, 3 * cm, 10 * cm])
        flag_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fef2f2")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#fecaca")),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("PADDING", (0, 0), (-1, -1), 3),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(flag_tbl)
    else:
        story.append(Paragraph("No flagged events in this window.", body))

    doc.build(story)
    buf.seek(0)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        io.BytesIO(buf.getvalue()),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=audit_report_{timestamp}.pdf"},
    )


# Batch eval — upload CSV of prompts, return verdict matrix
@app.post("/api/batch/run", dependencies=[Depends(_auth.require_admin)])
async def batch_run(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a CSV with a 'prompt' column (or one prompt per line if no
    header). For each prompt, run the active guardrail and return verdict +
    breakdown. Skips the LLM call — guardrail-only eval, optimised for speed
    on 100+ prompts."""
    import csv
    import io as _io

    from .guardrail_provider import GUARDRAIL_PROVIDERS, active_provider_id

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


# Provider health checks — ping every configured LLM + guardrail
@app.get("/api/health/providers", dependencies=[Depends(_auth.require_admin)])
async def health_providers(db: Session = Depends(get_db)):
    """For each configured LLM provider, send a 1-token "ping" request; for
    each configured guardrail, run a benign 1-word check. Returns up/down +
    latency per provider so the Admin Console can show a status panel.
    """
    import asyncio as _aio
    import time as _t

    from .guardrail_provider import GUARDRAIL_PROVIDERS
    from .providers import PROVIDERS, provider_api_key

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

    llm_tasks = [_llm_check(pid) for pid in PROVIDERS.keys()]
    guard_tasks = [_guard_check(pid, p) for pid, p in GUARDRAIL_PROVIDERS.items()]
    results = await _aio.gather(*(llm_tasks + guard_tasks), return_exceptions=False)
    return {"providers": results}


# Compare-All LLMs — fan a prompt to multiple LLM providers in parallel
@app.post("/api/chat/compare-llms", dependencies=[Depends(_auth.require_admin)])
async def compare_llms(payload: dict, db: Session = Depends(get_db)):
    """Run the same prompt through multiple LLM providers (each with its own
    model + key as configured in AppConfig) and return per-provider response,
    latency, tokens, and estimated cost. Sequential per provider to keep memory
    use low, but each call honours the same /api/chat path so guardrails and
    tools still fire.

    Body: { message: str, providers: [{provider, model}], session_id?: str }
    """
    import asyncio as _aio
    import time as _t

    from .providers import PROVIDERS

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

    results = await _aio.gather(*[_run_one(p) for p in requested])
    return {"message": message, "results": results}


# Guardrail compare — fan a prompt out to every configured guardrail provider
@app.post("/api/chat/compare-guardrails", dependencies=[Depends(_auth.require_admin)])
async def compare_guardrails(request: ChatRequest, db: Session = Depends(get_db)):
    """Run the user's message through every configured guardrail provider in
    parallel and return per-provider verdicts (with latency).

    Used by the Admin → Compare matrix to show how each vendor sees the same
    payload. Does NOT call the LLM — guardrail check only."""
    import asyncio as _aio
    import time as _t

    from .guardrail_provider import GUARDRAIL_PROVIDERS

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

    tasks = [_run_one(pid, p) for pid, p in GUARDRAIL_PROVIDERS.items()]
    results = await _aio.gather(*tasks)
    return {"message": request.message, "results": results}


# Image moderation
@app.post("/api/moderation/image", dependencies=[Depends(_auth.require_admin)])
async def moderate_image(payload: dict, db: Session = Depends(get_db)):
    """Scan an image with the active guardrail provider.

    Body: { "image_data_url": "data:image/png;base64,..." }
    Returns the same Lakera-shaped status the chat path uses, with an extra
    `supported: bool` so the UI can show a clear "not supported by this
    provider" badge instead of an empty result.
    """
    from .guardrail_provider import GUARDRAIL_PROVIDERS, active_provider_id

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


# Audit log endpoints
@app.get("/api/audit", dependencies=[Depends(_auth.require_admin)])
async def get_audit_log(
    format: str = "json",
    limit: int = 200,
    offset: int = 0,
    flagged_only: bool = False,
    session_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Return audit_log rows. format=csv returns text/csv attachment."""
    entries = audit.list_entries(
        db,
        limit=min(max(limit, 1), 1000),
        offset=max(offset, 0),
        flagged_only=flagged_only,
        session_id=session_id,
    )
    if format == "csv":
        csv_text = audit.to_csv(entries)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return StreamingResponse(
            io.BytesIO(csv_text.encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=audit_{timestamp}.csv"},
        )
    return {"entries": entries, "count": len(entries)}


@app.delete("/api/audit", dependencies=[Depends(_auth.require_admin)])
async def clear_audit_log(db: Session = Depends(get_db)):
    """Wipe audit_log entries (admin / demo-reset only)."""
    deleted = db.query(AuditLog).delete()
    db.commit()
    return {"deleted": deleted}


@app.get("/api/audit/stream")
async def audit_stream_endpoint(
    token: Optional[str] = Query(None, description="JWT (EventSource can't set headers)"),
    flagged_only: bool = Query(True, description="Default: only flagged events. Set false for all turns."),
):
    """Server-Sent Events feed of audit rows as they're written.

    The browser EventSource API can't attach an Authorization header, so we
    accept the JWT as a `?token=` query parameter and validate it manually.
    """
    import asyncio

    _auth.verify_token(token)
    q = audit_stream.subscribe()

    async def gen():
        try:
            # Initial handshake so the client knows it's connected.
            yield f"event: hello\ndata: {json.dumps({'subscribers': audit_stream.subscriber_count()})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Keep-alive comment so proxies don't reap idle connections.
                    yield ": keep-alive\n\n"
                    continue
                if flagged_only and not event.get("guardrail_flagged"):
                    continue
                yield f"event: audit\ndata: {json.dumps(event)}\n\n"
        finally:
            audit_stream.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# Conversation (multi-turn memory) endpoints
@app.get("/api/conversations", dependencies=[Depends(_auth.require_admin)])
async def list_conversations(limit: int = 50, db: Session = Depends(get_db)):
    rows = (
        db.query(Conversation)
        .order_by(Conversation.updated_at.desc())
        .limit(min(max(limit, 1), 200))
        .all()
    )
    return {
        "conversations": [
            {
                "id": r.id,
                "title": r.title,
                "session_id": r.session_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
    }


@app.get("/api/conversations/{conversation_id}", dependencies=[Depends(_auth.require_admin)])
async def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.id.asc())
        .all()
    )
    return {
        "id": conv.id,
        "title": conv.title,
        "session_id": conv.session_id,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "flagged": bool(m.flagged),
                "guardrail_status": m.guardrail_status,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in msgs
        ],
    }


@app.delete("/api/conversations/{conversation_id}", dependencies=[Depends(_auth.require_admin)])
async def delete_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.query(Message).filter(Message.conversation_id == conversation_id).delete()
    db.delete(conv)
    db.commit()
    return {"deleted": conversation_id}


# Scenario endpoints — one-click demo company switcher on the Landing page
_SCENARIO_PREVIEW_FIELDS = (
    "id",
    "industry",
    "business_name",
    "tagline",
    "hero_text",
    "theme",
    "logo_url",
    "hero_image_url",
)


@app.get("/api/scenarios")
async def list_scenarios():
    """List available one-click demo scenarios (branding-level preview only)."""
    return {
        "scenarios": [
            {field: scenario.get(field) for field in _SCENARIO_PREVIEW_FIELDS}
            for scenario in SCENARIOS
        ]
    }


@app.post("/api/scenarios/{scenario_id}/apply", dependencies=[Depends(_auth.require_admin)])
async def apply_scenario(scenario_id: str, db: Session = Depends(get_db)):
    """Apply a scenario: update AppConfig branding/persona and replace demo prompts."""
    scenario = get_scenario(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")

    config = db.query(AppConfig).first()
    if not config:
        config = AppConfig()
        db.add(config)
        db.flush()

    config.business_name = scenario["business_name"]
    config.tagline = scenario["tagline"]
    config.hero_text = scenario["hero_text"]
    config.logo_url = scenario["logo_url"]
    config.hero_image_url = scenario["hero_image_url"]
    config.theme = scenario["theme"]
    config.system_prompt = scenario["system_prompt"]

    db.query(DemoPrompt).delete()
    for prompt in scenario.get("demo_prompts", []):
        db.add(
            DemoPrompt(
                title=prompt["title"],
                content=prompt["content"],
                category=prompt.get("category", "general"),
                tags=prompt.get("tags", []),
                is_malicious=prompt.get("is_malicious", False),
                preferred_llm=prompt.get("preferred_llm"),
            )
        )

    db.commit()
    return {
        "message": f"Scenario '{scenario_id}' applied",
        "scenario_id": scenario_id,
        "business_name": scenario["business_name"],
        "prompts_loaded": len(scenario.get("demo_prompts", [])),
    }
