"""Tests for runner/branch_speculator.py"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["ORCH_BRANCH_SPECULATOR_ENABLED"] = "false"
os.environ["ORCH_DB_URL"] = ""
os.environ["ORCH_DB_ENABLED"] = "false"

import branch_speculator


def test_should_speculate_returns_bool_equivalent():
    """should_speculate returns dict with 'speculate' bool field."""
    task = {"kind": "feature", "difficulty": "standard", "slug": "add-feature-xyz"}
    result = branch_speculator.should_speculate(task, attempt=1)
    assert isinstance(result, dict)
    assert "speculate" in result
    assert isinstance(result["speculate"], bool)
    assert "reason" in result
    # Disabled, so should not speculate
    assert result["speculate"] is False
    assert result["reason"] == "disabled"


def test_generate_strategies_returns_list_of_3():
    """generate_strategies returns a list of strategy dicts (default 3 variants)."""
    task = {"kind": "feature", "slug": "fix-bug-abc"}
    prompt = "Fix the authentication bug in login.py"
    result = branch_speculator.generate_strategies(task, prompt, "/tmp/repo")
    assert isinstance(result, list)
    assert len(result) == 3
    names = [s["name"] for s in result]
    assert "conservative" in names
    assert "aggressive" in names
    assert "creative" in names
    # Each strategy should have a modified prompt
    for s in result:
        assert "prompt" in s
        assert prompt in s["prompt"]
        assert "model" in s


def test_pick_winner_selects_smallest_passing():
    """pick_winner selects the result with smallest diff among passing ones."""
    results = [
        {"strategy": "conservative", "rc": 0, "diff": "line1\nline2\nline3\n", "cost_usd": 0.03},
        {"strategy": "aggressive", "rc": 0, "diff": "line1\n", "cost_usd": 0.05},
        {"strategy": "creative", "rc": 1, "diff": "line1\nline2\n", "cost_usd": 0.08},
    ]
    result = branch_speculator.pick_winner(results)
    assert isinstance(result, dict)
    assert "winner" in result
    assert result["winner"] is not None
    # Aggressive has smallest diff (1 line) among passing (rc==0)
    assert result["winner"]["strategy"] == "aggressive"


def test_pick_winner_no_passing():
    """pick_winner returns winner=None when no result passes tests."""
    results = [
        {"strategy": "conservative", "rc": 1, "diff": "x\n"},
        {"strategy": "aggressive", "rc": 1, "diff": "y\n"},
    ]
    result = branch_speculator.pick_winner(results)
    assert result["winner"] is None
    assert "no variant passed" in result["reason"]
