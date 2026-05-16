"""Tests for backend.playbooks — catalog integrity for OWASP + POC checklist.

These integrity tests guard against the easy regressions:
  - accidentally removing a category from a published taxonomy
  - shipping a prompt without an `expected` outcome (UI scoring breaks)
  - shipping the POC playbook without enough golden-path coverage
"""

from backend.playbooks import PLAYBOOKS, get_playbook, is_builtin, list_playbooks

# ---------- catalog --------------------------------------------------------

def test_at_least_two_playbooks_shipped():
    """OWASP Top 10 + POC verification — drop below 2 and the dropdown looks broken."""
    assert len(PLAYBOOKS) >= 2


def test_list_playbooks_shape():
    catalog = list_playbooks()
    for entry in catalog:
        assert {"id", "name", "count"} <= set(entry.keys())
        assert entry["count"] >= 1


def test_list_playbooks_marks_builtins():
    """Custom DB rows are merged in the route handler — the function-level
    catalog must always flag entries as built-in so the UI can hide
    edit/delete on them."""
    for entry in list_playbooks():
        assert entry.get("is_builtin") is True


def test_get_playbook_returns_none_for_unknown():
    assert get_playbook("does-not-exist") is None


def test_is_builtin_helper():
    assert is_builtin("owasp_llm_top10_2025") is True
    assert is_builtin("poc_verification") is True
    assert is_builtin("custom_acme_inc") is False
    assert is_builtin("") is False


# ---------- shared schema validation ---------------------------------------

def test_every_prompt_has_required_fields():
    """Runner pulls these fields with item.get(...); missing ones silently
    produce blank UI cells."""
    required = {"id", "category", "prompt"}
    for pb in PLAYBOOKS.values():
        for prompt in pb["prompts"]:
            missing = required - set(prompt.keys())
            assert not missing, f"{pb['id']}::{prompt.get('id')} missing fields: {missing}"


def test_every_prompt_has_expected_outcome():
    """Pass/fail scoring needs `expected`. Allow either value but not None/missing."""
    for pb in PLAYBOOKS.values():
        for prompt in pb["prompts"]:
            expected = prompt.get("expected")
            assert expected in ("blocked", "allowed"), (
                f"{pb['id']}::{prompt['id']} has invalid expected={expected!r}"
            )


def test_prompt_ids_unique_within_playbook():
    for pb in PLAYBOOKS.values():
        ids = [p["id"] for p in pb["prompts"]]
        assert len(ids) == len(set(ids)), f"{pb['id']} has duplicate prompt IDs"


# ---------- OWASP playbook --------------------------------------------------

def test_owasp_playbook_has_ten_items():
    """It's literally called 'Top 10' — anything else is a bug."""
    pb = get_playbook("owasp_llm_top10_2025")
    assert pb is not None
    assert len(pb["prompts"]) == 10


def test_owasp_prompts_all_expect_blocked():
    """OWASP scenarios are all attacks — every one should fire the guardrail."""
    pb = get_playbook("owasp_llm_top10_2025")
    for prompt in pb["prompts"]:
        assert prompt["expected"] == "blocked", (
            f"OWASP entry {prompt['id']} expected blocked, got {prompt['expected']!r}"
        )


def test_owasp_ids_follow_llm_nn_convention():
    pb = get_playbook("owasp_llm_top10_2025")
    for prompt in pb["prompts"]:
        assert prompt["id"].startswith("LLM"), f"OWASP id {prompt['id']!r} should start with 'LLM'"


# ---------- POC verification playbook --------------------------------------

def test_poc_playbook_present():
    assert get_playbook("poc_verification") is not None


def test_poc_playbook_has_golden_path_section():
    """Need allowed-prompts to verify the guardrail doesn't over-block."""
    pb = get_playbook("poc_verification")
    allowed = [p for p in pb["prompts"] if p["expected"] == "allowed"]
    assert len(allowed) >= 5, "POC needs at least 5 expected-allowed prompts"


def test_poc_playbook_has_blocked_section():
    pb = get_playbook("poc_verification")
    blocked = [p for p in pb["prompts"] if p["expected"] == "blocked"]
    assert len(blocked) >= 10, "POC needs at least 10 expected-blocked prompts"


def test_poc_playbook_covers_all_five_categories():
    """The whole point of the POC checklist is breadth across attack types."""
    pb = get_playbook("poc_verification")
    categories = {p["category"] for p in pb["prompts"]}
    expected = {
        "Golden path",
        "PII coverage",
        "False-positive checks",
        "Injection variants",
        "Encoding / evasion",
    }
    missing = expected - categories
    assert not missing, f"POC missing categories: {missing}"


def test_poc_pii_section_covers_common_detectors():
    """Lakera/Bedrock ship ~7-8 PII detectors; we want a prompt per type."""
    pb = get_playbook("poc_verification")
    pii_prompts = [p for p in pb["prompts"] if p["category"] == "PII coverage"]
    assert len(pii_prompts) >= 7, (
        f"PII section has {len(pii_prompts)} prompts; want ≥7 to cover the detectors"
    )


def test_poc_ids_namespaced():
    pb = get_playbook("poc_verification")
    for prompt in pb["prompts"]:
        assert prompt["id"].startswith("POC-"), (
            f"POC entry {prompt['id']!r} should start with 'POC-'"
        )
