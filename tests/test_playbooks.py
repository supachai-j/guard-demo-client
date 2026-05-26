"""Tests for backend.playbooks — catalog integrity for the OWASP built-in.

POC verification integrity tests moved to tests/test_seed_poc_verification_playbook.py
(it's now a seed script, not a built-in).

These integrity tests guard against the easy regressions:
  - accidentally removing a category from a published taxonomy
  - shipping a prompt without an `expected` outcome (UI scoring breaks)
"""

from backend.playbooks import PLAYBOOKS, get_playbook, is_builtin, list_playbooks

# ---------- catalog --------------------------------------------------------

def test_owasp_is_the_built_in():
    """OWASP Top 10 is the only built-in. Other suites (POC, AIGW policy) seed via scripts/."""
    assert "owasp_llm_top10_2025" in PLAYBOOKS
    assert len(PLAYBOOKS) >= 1


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
    # POC was moved to a seed script — must not register as built-in anymore.
    assert is_builtin("poc_verification") is False
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


# POC integrity tests live in tests/test_seed_poc_verification_playbook.py now.
