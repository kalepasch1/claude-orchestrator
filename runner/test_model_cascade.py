"""Tests for runner/model_cascade.py"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["ORCH_MODEL_CASCADE"] = "true"
os.environ["ORCH_DB_URL"] = ""
os.environ["ORCH_DB_ENABLED"] = "false"

import model_cascade


def test_should_cascade_returns_dict_with_model_and_chain():
    """should_cascade returns dict with start_model and escalation_chain."""
    task = {"kind": "feature", "difficulty": "standard"}
    result = model_cascade.should_cascade(task)
    assert isinstance(result, dict)
    assert "start_model" in result
    assert "escalation_chain" in result
    assert isinstance(result["escalation_chain"], list)
    assert len(result["escalation_chain"]) > 0


def test_should_cascade_hard_skips_cheapest():
    """Hard tasks should skip the cheapest model in the chain."""
    task = {"kind": "feature", "difficulty": "hard"}
    result = model_cascade.should_cascade(task)
    # Hard tasks start at index 1 (gemini-flash), not index 0
    assert result["start_model"] == model_cascade.ESCALATION_CHAIN[1]


def test_record_cascade_outcome_no_crash():
    """record_cascade_outcome should not crash on valid input."""
    model_cascade.invalidate()
    task = {"kind": "test", "difficulty": "standard"}
    model_cascade.record_cascade_outcome(
        task, "deepseek-v4-flash", False, "deepseek-v4-flash", True, 0.001
    )
    model_cascade.record_cascade_outcome(
        task, "deepseek-v4-flash", True, "claude-sonnet", True, 0.02
    )
    # Should not raise; stats should reflect the recordings
    s = model_cascade.stats()
    assert s["total_cascades"] == 2
    assert s["total_saves"] == 1
    assert s["total_escalations"] == 1


def test_cascade_classify_refusal_escalates():
    """Refusal language in first tokens should lower confidence and may trigger escalation."""
    model_cascade.invalidate()
    task = {"kind": "feature", "difficulty": "hard", "model": "deepseek-v4-flash"}
    result = model_cascade.cascade_classify(
        task, "I can't handle this, I'm unable to complete this complex task"
    )
    assert isinstance(result, dict)
    assert "confidence" in result
    assert "escalate" in result
    assert "reason" in result
    # Refusal signals + hard-on-cheap should push confidence down
    assert result["confidence"] < 0.6
    assert result["escalate"] is True


def test_stats_returns_expected_keys():
    """stats() returns dict with cascade effectiveness metrics."""
    model_cascade.invalidate()
    result = model_cascade.stats()
    assert isinstance(result, dict)
    for key in ("cascade_saves_pct", "avg_escalation_depth", "total_saved_usd",
                "total_cascades", "total_escalations", "total_saves"):
        assert key in result, f"Missing key: {key}"
