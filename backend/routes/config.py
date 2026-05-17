"""App config GET/PUT + selective ZIP export/import.

Most of the bulk in this module is the import_config handler — it has
to cope with two on-disk formats (v1.0 full-replace, v2.0 section-merge)
plus the legacy "demo prompts live in agentic_demo.db inside the ZIP"
shape that some early exports used.
"""

import io
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import auth as _auth
from .. import llm_client
from ..config_redaction import redact_config
from ..database import get_db
from ..models import AppConfig, DemoPrompt, MCPToolCapabilities, RagSource, Tool
from ..schemas import AppConfigResponse, AppConfigUpdate

router = APIRouter(tags=["config"])


# Export sections: which config fields belong to which section (for selective export/import)
# Fields locked when AppConfig.provider_config_locked = True. Edits to any
# of these via PUT /api/config or POST /api/config/import return 403; the
# lock toggle itself is intentionally excluded so the operator can still
# unlock. Keep this list in sync with the AppConfig model — new provider
# fields must be added here or the lock silently lets them through.
PROVIDER_CONFIG_FIELDS = frozenset([
    # LLM provider selection + model + per-provider keys
    "llm_provider", "openai_model", "use_litellm",
    "openai_api_key", "anthropic_api_key", "google_api_key",
    "mistral_api_key", "groq_api_key", "together_api_key",
    "openrouter_api_key", "ollama_base_url",
    # LiteLLM proxy
    "litellm_base_url", "litellm_virtual_key",
    "litellm_guardrail_name", "litellm_guardrail_monitor_name",
    # Portkey
    "portkey_api_key", "portkey_virtual_key", "portkey_base_url",
    # Guardrail provider selection + per-provider config
    "guardrail_provider",
    "lakera_api_key", "lakera_project_id", "lakera_enabled", "lakera_blocking_mode",
    "rag_lakera_project_id",
    "bedrock_guardrail_id", "bedrock_guardrail_version", "bedrock_region",
    "bedrock_access_key_id", "bedrock_secret_access_key",
    "azure_content_safety_endpoint", "azure_content_safety_key",
    "palo_alto_api_key", "palo_alto_profile_name", "palo_alto_host",
    "cloudflare_account_id", "cloudflare_api_token", "cloudflare_gateway_id",
])

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


@router.get("/api/config", response_model=AppConfigResponse)
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
    return redact_config(config, authenticated=bool(user))


@router.put("/api/config", response_model=AppConfigResponse, dependencies=[Depends(_auth.require_admin)])
async def update_config(config_update: AppConfigUpdate, db: Session = Depends(get_db)):
    config = db.query(AppConfig).first()
    if not config:
        config = AppConfig()
        db.add(config)

    payload = config_update.dict(exclude_unset=True)

    # Demo-safe lock — when the stored row says provider_config_locked=True,
    # reject any attempt to CHANGE a provider-related field. We compare value
    # (not just key presence) so the existing frontend pattern of "send all
    # fields every save" still works for non-provider edits (theme, prompt,
    # webhook) and for the unlock toggle itself.
    if config.provider_config_locked:
        actual_changes = {
            k for k in (PROVIDER_CONFIG_FIELDS & set(payload.keys()))
            if payload[k] != getattr(config, k, None)
        }
        if actual_changes:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Provider config is locked. Unlock first to change: "
                    f"{sorted(actual_changes)}"
                ),
            )

    # Update fields
    for field, value in payload.items():
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


@router.get("/api/config/export", dependencies=[Depends(_auth.require_admin)])
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
                from ..rag import get_chroma_export_path

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


@router.post("/api/config/import", dependencies=[Depends(_auth.require_admin)])
async def import_config(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import configuration from a zip file. Supports v1.0 (full replace) and v2.0 (merge by section)."""
    try:
        if not file.filename.endswith(".zip"):
            raise HTTPException(status_code=400, detail="File must be a .zip file")
        file_content = await file.read()

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
                        from ..rag import reinitialize_chromadb

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
                # Respect demo-safe lock — import that would touch any provider
                # field is rejected wholesale (no partial import) so the
                # operator sees a clean 403 instead of silent partial state.
                if config_row.provider_config_locked:
                    blocked_fields: set = set()
                    for section, fields in EXPORT_SECTIONS.items():
                        if section not in includes:
                            continue
                        for field in fields:
                            if field in config_data and field in PROVIDER_CONFIG_FIELDS:
                                blocked_fields.add(field)
                    if blocked_fields:
                        raise HTTPException(
                            status_code=403,
                            detail=(
                                f"Provider config is locked. Unlock first to import: "
                                f"{sorted(blocked_fields)}"
                            ),
                        )
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
                        from ..rag import reinitialize_chromadb

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


# Legacy export/import — kept for backward compatibility, not used by current UI.
@router.get("/api/export")
async def legacy_export_config(db: Session = Depends(get_db)):
    config = db.query(AppConfig).first()
    tools = db.query(Tool).all()
    rag_sources = db.query(RagSource).all()

    return {"config": config, "tools": tools, "rag_sources": rag_sources}


@router.post("/api/import")
async def legacy_import_config(data: dict, db: Session = Depends(get_db)):
    # Placeholder for import functionality
    return {"message": "Import functionality needs to be implemented"}
