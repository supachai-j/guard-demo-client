import logging
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .database import engine
from .models import Base

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


# Route modules — extracted from this file to keep it from growing. Each
# router carries its own prefix; add new endpoints in the matching module.
from .routes import audit as _audit_routes  # noqa: E402
from .routes import auth as _auth_routes  # noqa: E402
from .routes import catalogs as _catalogs_routes  # noqa: E402
from .routes import chat as _chat_routes  # noqa: E402
from .routes import config as _config_routes  # noqa: E402
from .routes import conversations as _conversations_routes  # noqa: E402
from .routes import demo_prompts as _demo_prompts_routes  # noqa: E402
from .routes import lakera_legacy as _lakera_legacy_routes  # noqa: E402
from .routes import playbooks as _playbooks_routes  # noqa: E402
from .routes import rag as _rag_routes  # noqa: E402
from .routes import recordings as _recordings_routes  # noqa: E402
from .routes import scenarios as _scenarios_routes  # noqa: E402
from .routes import system as _system_routes  # noqa: E402
from .routes import threat_lab as _threat_lab_routes  # noqa: E402
from .routes import tools as _tools_routes  # noqa: E402

app.include_router(_system_routes.router)
app.include_router(_auth_routes.router)
app.include_router(_config_routes.router)
app.include_router(_catalogs_routes.router)
app.include_router(_chat_routes.router)
app.include_router(_conversations_routes.router)
app.include_router(_rag_routes.router)
app.include_router(_demo_prompts_routes.router)
app.include_router(_tools_routes.router)
app.include_router(_scenarios_routes.router)
app.include_router(_lakera_legacy_routes.router)
app.include_router(_recordings_routes.router)
app.include_router(_playbooks_routes.router)
app.include_router(_audit_routes.router)
app.include_router(_threat_lab_routes.router)


# Re-export from the tiny config_redaction module so tests can import the
# mask list without loading the full FastAPI app (which pulls in chromadb +
# numpy, occasionally CPU-incompatible on CI).
from .config_redaction import redact_config as _config_response  # noqa: E402, F401
