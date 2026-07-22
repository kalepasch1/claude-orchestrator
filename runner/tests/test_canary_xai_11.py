"""Canary test: approval_policy pure-function smoke tests (xai-11)."""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_build_decision_prompt_basic():
    """build_decision_prompt returns structured dict with question and options."""
    from approval_policy import build_decision_prompt
    card = {"title": "Test card", "why": "Should we proceed?"}
    alts = [{"label": "Yes", "risk": "low", "reversible": True, "recommended": True}]
    result = build_decision_prompt(card, alts)
    assert "question" in result
    assert "options" in result
    assert len(result["options"]) == 1
    assert "Yes" in result["options"][0]["label"]


def test_build_decision_prompt_auto_recommend():
    """When no option is marked recommended, lowest-risk reversible wins."""
    from approval_policy import build_decision_prompt
    card = {"title": "X"}
    alts = [
        {"label": "High", "risk": "high", "reversible": False},
        {"label": "Low", "risk": "low", "reversible": True},
    ]
    result = build_decision_prompt(card, alts)
    assert result["recommended_index"] == 1


def test_build_decision_prompt_empty_alts():
    """Empty alternatives list produces empty options."""
    from approval_policy import build_decision_prompt
    result = build_decision_prompt({"title": "T"}, [])
    assert result["options"] == []
