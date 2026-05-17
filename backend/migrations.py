"""Idempotent SQLite schema migrations.

Each migration is `ALTER TABLE ... ADD COLUMN` guarded by a PRAGMA
table_info check, so re-running on a current DB is a no-op. New columns
go at the bottom; never reorder or delete blocks (existing prod DBs only
move forward through this list).

Call `run_migrations()` once at startup, after `Base.metadata.create_all`.
"""

from sqlalchemy import text

from .database import engine


def _existing_columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def _migrate_app_config_litellm():
    """Add use_litellm and litellm_base_url to app_config if missing (existing DBs)."""
    with engine.connect() as conn:
        columns = _existing_columns(conn, "app_config")
        if "use_litellm" not in columns:
            conn.execute(text("ALTER TABLE app_config ADD COLUMN use_litellm BOOLEAN DEFAULT 0"))
            conn.commit()
        if "litellm_base_url" not in columns:
            conn.execute(text("ALTER TABLE app_config ADD COLUMN litellm_base_url VARCHAR"))
            conn.commit()


def _migrate_demo_prompts_preferred_llm():
    """Add preferred_llm to demo_prompts if missing (existing DBs)."""
    with engine.connect() as conn:
        columns = _existing_columns(conn, "demo_prompts")
        if "preferred_llm" not in columns:
            conn.execute(text("ALTER TABLE demo_prompts ADD COLUMN preferred_llm VARCHAR"))
            conn.commit()


def _migrate_app_config_theme():
    """Add theme to app_config if missing (for UI theming)."""
    with engine.connect() as conn:
        columns = _existing_columns(conn, "app_config")
        if "theme" not in columns:
            conn.execute(text("ALTER TABLE app_config ADD COLUMN theme VARCHAR"))
            conn.execute(text("UPDATE app_config SET theme = 'blue' WHERE theme IS NULL"))
            conn.commit()


def _migrate_app_config_litellm_virtual_key():
    """Add litellm_virtual_key; one-time copy from openai_api_key for existing
    LiteLLM rows that used the old single field."""
    with engine.connect() as conn:
        columns = _existing_columns(conn, "app_config")
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


def _migrate_app_config_litellm_guardrail_fields():
    """Add LiteLLM guardrail fields for block/monitor naming if missing."""
    with engine.connect() as conn:
        columns = _existing_columns(conn, "app_config")
        if "litellm_guardrail_name" not in columns:
            conn.execute(text("ALTER TABLE app_config ADD COLUMN litellm_guardrail_name VARCHAR"))
            conn.commit()
        if "litellm_guardrail_monitor_name" not in columns:
            conn.execute(text("ALTER TABLE app_config ADD COLUMN litellm_guardrail_monitor_name VARCHAR"))
            conn.commit()


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
        columns = _existing_columns(conn, "app_config")
        for name, col_type in new_columns.items():
            if name not in columns:
                conn.execute(text(f"ALTER TABLE app_config ADD COLUMN {name} {col_type}"))
                conn.commit()
        # Backfill llm_provider for existing rows: use_litellm=1 → litellm_proxy, else openai.
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


def _migrate_app_config_openrouter():
    """Add openrouter_api_key column for existing DBs."""
    with engine.connect() as conn:
        columns = _existing_columns(conn, "app_config")
        if "openrouter_api_key" not in columns:
            conn.execute(text("ALTER TABLE app_config ADD COLUMN openrouter_api_key VARCHAR"))
            conn.commit()


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
        columns = _existing_columns(conn, "app_config")
        for name, col_type in new_columns.items():
            if name not in columns:
                conn.execute(text(f"ALTER TABLE app_config ADD COLUMN {name} {col_type}"))
                conn.commit()
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


def _migrate_app_config_portkey_base_url():
    """Add portkey_base_url for self-managed Portkey deployments."""
    with engine.connect() as conn:
        columns = _existing_columns(conn, "app_config")
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
        columns = _existing_columns(conn, "app_config")
        for name, col_type in new_columns.items():
            if name not in columns:
                conn.execute(text(f"ALTER TABLE app_config ADD COLUMN {name} {col_type}"))
                conn.commit()


def _migrate_app_config_webhook():
    """Add webhook_url for outbound flag notifications."""
    with engine.connect() as conn:
        columns = _existing_columns(conn, "app_config")
        if "webhook_url" not in columns:
            conn.execute(text("ALTER TABLE app_config ADD COLUMN webhook_url VARCHAR"))
            conn.commit()


def _migrate_audit_log_tokens():
    """Add token / cost columns to audit_log."""
    with engine.connect() as conn:
        columns = _existing_columns(conn, "audit_log")
        for name, ctype in [("input_tokens", "INTEGER"), ("output_tokens", "INTEGER"), ("cost_usd", "VARCHAR")]:
            if name not in columns:
                conn.execute(text(f"ALTER TABLE audit_log ADD COLUMN {name} {ctype}"))
                conn.commit()


# Order matters: later migrations may reference columns added by earlier ones
# (e.g. multi_provider backfills from use_litellm).
_MIGRATIONS = [
    _migrate_app_config_litellm,
    _migrate_demo_prompts_preferred_llm,
    _migrate_app_config_theme,
    _migrate_app_config_litellm_virtual_key,
    _migrate_app_config_litellm_guardrail_fields,
    _migrate_app_config_multi_provider,
    _migrate_app_config_openrouter,
    _migrate_app_config_guardrail_provider,
    _migrate_app_config_portkey_base_url,
    _migrate_app_config_cloudflare,
    _migrate_app_config_webhook,
    _migrate_audit_log_tokens,
]


def run_migrations() -> None:
    """Apply all idempotent schema migrations in order."""
    for migration in _MIGRATIONS:
        migration()
