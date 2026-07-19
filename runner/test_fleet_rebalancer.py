"""Tests for runner/fleet_rebalancer.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set env vars before import to disable DB calls
os.environ["ORCH_FLEET_REBALANCER_ENABLED"] = "true"
os.environ["ORCH_DB_URL"] = ""
os.environ["ORCH_SUPABASE_URL"] = ""
os.environ["ORCH_SUPABASE_KEY"] = ""

import fleet_rebalancer


def test_register_activity_does_not_crash():
    """register_activity should accept arguments without raising."""
    fleet_rebalancer.register_activity("runner-1", "proj-A", "task-100", "RUNNING")
    fleet_rebalancer.register_activity("runner-2", "proj-B", "task-200", "IDLE")
    fleet_rebalancer.register_activity("runner-1", "proj-A", "task-100", "DONE")
    # No assertion needed — just verifying no exception


def test_assess_balance_returns_dict():
    """assess_balance should return a dict with expected keys."""
    result = fleet_rebalancer.assess_balance()
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "balanced" in result, "Missing 'balanced' key"
    assert "imbalances" in result, "Missing 'imbalances' key"
    assert "recommendations" in result, "Missing 'recommendations' key"


def test_rebalance_returns_dict_with_action_key():
    """rebalance should return a dict with an 'action' key."""
    result = fleet_rebalancer.rebalance("runner-1", ["proj-A"])
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "action" in result, "Missing 'action' key"
    assert result["action"] in ("stay", "redirect"), f"Unexpected action: {result['action']}"


def test_idle_time_returns_float():
    """idle_time should return a float >= 0."""
    fleet_rebalancer.register_activity("runner-idle", "proj-X", "task-1", "RUNNING")
    result = fleet_rebalancer.idle_time("runner-idle")
    assert isinstance(result, (int, float)), f"Expected numeric, got {type(result)}"
    assert result >= 0, f"idle_time should be non-negative, got {result}"


def test_stats_returns_dict():
    """stats should return a dict with enabled key."""
    result = fleet_rebalancer.stats()
    assert isinstance(result, dict)
    assert "enabled" in result
    assert result["enabled"] is True
