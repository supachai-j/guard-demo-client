"""Integrity tests for scripts/seed_poc_verification_playbook.py.

POC verification was a built-in in backend/playbooks.py; after it moved to
a seed script, these tests still pin the same guarantees that mattered as
a built-in — the seed script is the single source of truth now, so a
re-org that breaks category coverage or PII breadth has to be deliberate.

Tests import the playbook dict directly, no DB roundtrip — keeps them
fast and orthogonal to the seed() function's DB write logic.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# The seed script lives outside the importable `backend` / `tests` packages,
# so load it as a module by file path.
_SEED_PATH = Path(__file__).resolve().parent.parent / "scripts" / "seed_poc_verification_playbook.py"
spec = importlib.util.spec_from_file_location("seed_poc_verification_playbook", _SEED_PATH)
seed_module = importlib.util.module_from_spec(spec)
sys.modules["seed_poc_verification_playbook"] = seed_module
spec.loader.exec_module(seed_module)

POC = seed_module._POC_PLAYBOOK
PROMPTS = POC["prompts"]


# ---------- shape ---------------------------------------------------------

def test_slug_and_name_present():
    assert POC["slug"] == "poc_verification"
    assert POC["name"] == "POC Verification Checklist"
    assert POC["description"]


def test_every_prompt_has_required_fields():
    """Runner pulls these fields with item.get(...); missing ones silently
    produce blank UI cells."""
    required = {"id", "category", "prompt", "expected"}
    for prompt in PROMPTS:
        missing = required - set(prompt.keys())
        assert not missing, f"{prompt.get('id')} missing fields: {missing}"


def test_every_prompt_has_valid_expected_outcome():
    for prompt in PROMPTS:
        assert prompt["expected"] in ("blocked", "allowed"), (
            f"{prompt['id']} has invalid expected={prompt['expected']!r}"
        )


def test_prompt_ids_unique():
    ids = [p["id"] for p in PROMPTS]
    assert len(ids) == len(set(ids)), "duplicate prompt IDs"


def test_ids_namespaced():
    for prompt in PROMPTS:
        assert prompt["id"].startswith("POC-"), (
            f"{prompt['id']!r} should start with 'POC-'"
        )


# ---------- breadth -------------------------------------------------------

def test_has_golden_path_coverage():
    """Need allowed-prompts to verify the guardrail doesn't over-block."""
    allowed = [p for p in PROMPTS if p["expected"] == "allowed"]
    assert len(allowed) >= 5, "POC needs at least 5 expected-allowed prompts"


def test_has_blocked_coverage():
    blocked = [p for p in PROMPTS if p["expected"] == "blocked"]
    assert len(blocked) >= 10, "POC needs at least 10 expected-blocked prompts"


def test_covers_all_five_categories():
    """The whole point of the POC checklist is breadth across attack types."""
    categories = {p["category"] for p in PROMPTS}
    expected = {
        "Golden path",
        "PII coverage",
        "False-positive checks",
        "Injection variants",
        "Encoding / evasion",
    }
    missing = expected - categories
    assert not missing, f"POC missing categories: {missing}"


def test_pii_section_covers_common_detectors():
    """Lakera/Bedrock ship ~7-8 PII detectors; we want a prompt per type."""
    pii_prompts = [p for p in PROMPTS if p["category"] == "PII coverage"]
    assert len(pii_prompts) >= 7, (
        f"PII section has {len(pii_prompts)} prompts; want ≥7 to cover the detectors"
    )
