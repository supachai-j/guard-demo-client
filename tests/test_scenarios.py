"""Tests for backend.scenarios — one-click company personas."""

from backend.scenarios import SCENARIOS, get_scenario


EXPECTED_IDS = {"credflow", "nimbusvault", "safeharbor", "vitalis"}


def test_four_scenarios_shipped():
    """The Landing page ScenarioSwitcher expects all four to be present."""
    ids = {s["id"] for s in SCENARIOS}
    assert ids == EXPECTED_IDS


def test_get_scenario_returns_correct_persona():
    s = get_scenario("credflow")
    assert s is not None
    assert s["id"] == "credflow"
    assert s["business_name"] == "CredFlow"


def test_get_scenario_returns_none_for_unknown():
    assert get_scenario("does-not-exist") is None
    assert get_scenario("") is None


def test_every_scenario_has_required_fields():
    """The branding apply flow assumes these keys exist."""
    required = {
        "id", "business_name", "tagline", "hero_text",
        "logo_url", "hero_image_url", "theme", "system_prompt", "demo_prompts",
    }
    for s in SCENARIOS:
        missing = required - set(s.keys())
        assert not missing, f"scenario {s.get('id')} missing fields: {missing}"


def test_every_scenario_has_at_least_one_demo_prompt():
    for s in SCENARIOS:
        assert isinstance(s["demo_prompts"], list)
        assert len(s["demo_prompts"]) >= 1, f"{s['id']} has no demo prompts"


def test_every_scenario_includes_a_malicious_prompt_for_security_demo():
    """The whole point of this product is to demonstrate guardrails — every
    persona should have at least one prompt flagged is_malicious so the
    demo operator can show the shield catching it."""
    for s in SCENARIOS:
        has_malicious = any(p.get("is_malicious") for p in s["demo_prompts"])
        assert has_malicious, f"{s['id']} has no malicious prompt for the security demo"


def test_logo_and_hero_urls_point_at_static_mount():
    """Images are served via the /static mount in main.py — URLs must use that prefix."""
    for s in SCENARIOS:
        assert s["logo_url"].startswith("/static/")
        assert s["hero_image_url"].startswith("/static/")
