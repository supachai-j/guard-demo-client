"""Idempotent SQLite schema migrations.

Each migration adds one column to a table; it's a no-op if the column
already exists. Optional `backfill` SQL runs after the ALTER (either only
when the column was just created, via `once=True`, or every startup with a
WHERE-idempotent UPDATE).

New columns go at the BOTTOM of `_MIGRATIONS`. Never reorder or delete
entries — existing prod DBs only move forward through this list.

Call `run_migrations()` once at startup, after `Base.metadata.create_all`.
"""

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text

from .database import engine


@dataclass(frozen=True)
class Migration:
    """One ADD COLUMN + optional backfill."""
    table: str
    column: str
    type: str
    backfill: Optional[str] = None  # SQL run after ALTER fires
    once: bool = False              # if True, backfill runs only when the column is first added;
                                    # otherwise it runs every startup (caller must use WHERE for idempotency)


# Order matters: later migrations may reference columns added by earlier
# ones (e.g. the multi_provider backfill reads use_litellm).
_MIGRATIONS = [
    Migration("app_config", "use_litellm", "BOOLEAN DEFAULT 0"),
    Migration("app_config", "litellm_base_url", "VARCHAR"),
    Migration("demo_prompts", "preferred_llm", "VARCHAR"),
    Migration(
        "app_config", "theme", "VARCHAR",
        backfill="UPDATE app_config SET theme = 'blue' WHERE theme IS NULL",
    ),
    Migration(
        "app_config", "litellm_virtual_key", "VARCHAR",
        # One-time copy from the old single openai_api_key field for legacy
        # LiteLLM rows. Guarded by `once=True` so re-running can't overwrite
        # a key the operator has since changed deliberately.
        backfill=(
            "UPDATE app_config "
            "SET litellm_virtual_key = openai_api_key "
            "WHERE use_litellm = 1 "
            "  AND (litellm_virtual_key IS NULL OR litellm_virtual_key = '') "
            "  AND openai_api_key IS NOT NULL AND openai_api_key != ''"
        ),
        once=True,
    ),
    Migration("app_config", "litellm_guardrail_name", "VARCHAR"),
    Migration("app_config", "litellm_guardrail_monitor_name", "VARCHAR"),
    # Multi-LLM-provider columns. The first one (llm_provider) carries the
    # backfill; the rest are simple ADDs that run in this same group.
    Migration(
        "app_config", "llm_provider", "VARCHAR",
        backfill=(
            "UPDATE app_config "
            "SET llm_provider = CASE WHEN use_litellm = 1 THEN 'litellm_proxy' ELSE 'openai' END "
            "WHERE llm_provider IS NULL OR llm_provider = ''"
        ),
    ),
    Migration("app_config", "anthropic_api_key", "VARCHAR"),
    Migration("app_config", "google_api_key", "VARCHAR"),
    Migration("app_config", "mistral_api_key", "VARCHAR"),
    Migration("app_config", "groq_api_key", "VARCHAR"),
    Migration("app_config", "together_api_key", "VARCHAR"),
    Migration("app_config", "ollama_base_url", "VARCHAR"),
    Migration("app_config", "openrouter_api_key", "VARCHAR"),
    # Multi-guardrail-provider columns + default.
    Migration(
        "app_config", "guardrail_provider", "VARCHAR",
        backfill="UPDATE app_config SET guardrail_provider = 'lakera' WHERE guardrail_provider IS NULL OR guardrail_provider = ''",
    ),
    Migration("app_config", "bedrock_guardrail_id", "VARCHAR"),
    Migration("app_config", "bedrock_guardrail_version", "VARCHAR"),
    Migration("app_config", "bedrock_region", "VARCHAR"),
    Migration("app_config", "bedrock_access_key_id", "VARCHAR"),
    Migration("app_config", "bedrock_secret_access_key", "VARCHAR"),
    Migration("app_config", "azure_content_safety_endpoint", "VARCHAR"),
    Migration("app_config", "azure_content_safety_key", "VARCHAR"),
    Migration("app_config", "palo_alto_api_key", "VARCHAR"),
    Migration("app_config", "palo_alto_profile_name", "VARCHAR"),
    Migration("app_config", "palo_alto_host", "VARCHAR"),
    Migration("app_config", "portkey_api_key", "VARCHAR"),
    Migration("app_config", "portkey_virtual_key", "VARCHAR"),
    Migration("app_config", "portkey_base_url", "VARCHAR"),
    Migration("app_config", "cloudflare_account_id", "VARCHAR"),
    Migration("app_config", "cloudflare_api_token", "VARCHAR"),
    Migration("app_config", "cloudflare_gateway_id", "VARCHAR"),
    Migration("app_config", "webhook_url", "VARCHAR"),
    Migration("audit_log", "input_tokens", "INTEGER"),
    Migration("audit_log", "output_tokens", "INTEGER"),
    Migration("audit_log", "cost_usd", "VARCHAR"),
]


def _existing_columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def run_migrations() -> None:
    """Apply all idempotent schema migrations in order."""
    with engine.connect() as conn:
        column_cache: dict[str, set[str]] = {}
        for m in _MIGRATIONS:
            if m.table not in column_cache:
                column_cache[m.table] = _existing_columns(conn, m.table)
            cols = column_cache[m.table]
            just_added = m.column not in cols
            if just_added:
                conn.execute(text(f"ALTER TABLE {m.table} ADD COLUMN {m.column} {m.type}"))
                cols.add(m.column)
            if m.backfill and (just_added or not m.once):
                conn.execute(text(m.backfill))
        conn.commit()
