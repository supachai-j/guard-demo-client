"""Security-regression tests — guard against shipping bugs that *look* like
features but quietly weaken the product's threat model.

Each test here was added in response to a real near-miss in the project.
Naming them after the incident keeps the institutional memory close to
the code:

  test_every_credential_column_is_in_mask_list  → OpenRouter mask-list miss
                                                  (2026-05-16 retro)
  test_default_admin_warning_actually_warns      → /api/auth/status shape
                                                  that the login banner relies on
"""

from __future__ import annotations

from backend.main import _SECRET_CONFIG_FIELDS
from backend.models import AppConfig
from sqlalchemy import inspect

# Substrings that indicate a column likely holds a credential. Anything in
# AppConfig matching one of these MUST appear in _SECRET_CONFIG_FIELDS so
# the public GET /api/config redacts it.
_CREDENTIAL_SUFFIXES = (
    "_api_key",
    "_virtual_key",
    "_secret",
    "_secret_access_key",
    "_access_key_id",
    "_token",
    "_password",  # future-proofing — none today
)

# Allow-list for columns that *match* the credential pattern but are NOT
# secrets. Empty for now. Add an entry with a one-line justification if you
# legitimately need one (e.g. a future `webhook_token_label` that names a
# token but doesn't store one).
_NON_SECRET_ALLOWLIST: set[str] = set()


def _credential_columns() -> set[str]:
    cols = {c.name for c in inspect(AppConfig).columns}
    suspects = {c for c in cols if any(c.endswith(s) for s in _CREDENTIAL_SUFFIXES)}
    # Also flag anything literally named "*_key" (broader than _api_key).
    suspects |= {c for c in cols if c.endswith("_key") and c not in suspects}
    return suspects - _NON_SECRET_ALLOWLIST


def test_every_credential_column_is_in_mask_list():
    """If you add a new credential column, you must also add it to
    `_SECRET_CONFIG_FIELDS` in backend/main.py. Forgetting once cost us
    a plaintext OpenRouter key in `GET /api/config` (caught in smoke,
    not by tests). This test makes the omission impossible to merge."""
    suspects = _credential_columns()
    missing = suspects - set(_SECRET_CONFIG_FIELDS)
    assert not missing, (
        f"AppConfig columns look like credentials but are NOT in "
        f"_SECRET_CONFIG_FIELDS: {sorted(missing)}.\n"
        f"Fix: add them to the tuple in backend/main.py, or to "
        f"_NON_SECRET_ALLOWLIST in this test (with a justification comment) "
        f"if they truly aren't secrets."
    )


def test_mask_list_only_references_real_columns():
    """The reverse direction — every name in _SECRET_CONFIG_FIELDS must
    correspond to an actual AppConfig column. Catches typos and references
    to columns that have been renamed/removed."""
    cols = {c.name for c in inspect(AppConfig).columns}
    bogus = set(_SECRET_CONFIG_FIELDS) - cols
    assert not bogus, f"_SECRET_CONFIG_FIELDS references non-existent columns: {sorted(bogus)}"


def test_mask_list_has_no_duplicates():
    """A duplicate is harmless but indicates someone added an entry twice
    — which usually means a copy/paste went wrong somewhere nearby."""
    assert len(_SECRET_CONFIG_FIELDS) == len(set(_SECRET_CONFIG_FIELDS)), (
        f"_SECRET_CONFIG_FIELDS has duplicates: "
        f"{[x for x in _SECRET_CONFIG_FIELDS if _SECRET_CONFIG_FIELDS.count(x) > 1]}"
    )


def test_auth_status_payload_shape():
    """Login banner relies on /api/auth/status returning these three fields.
    Renaming any of them silently breaks the warn-default-password UX."""
    from backend.auth import auth_status

    payload = auth_status()
    assert set(payload.keys()) == {"enabled", "default_user", "warn_default_password"}
    assert isinstance(payload["enabled"], bool)
    assert isinstance(payload["warn_default_password"], bool)
