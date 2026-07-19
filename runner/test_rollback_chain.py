"""Tests for runner/rollback_chain.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable to avoid actual git operations
os.environ["ORCH_ROLLBACK_CHAIN_ENABLED"] = "false"
os.environ["ORCH_DB_URL"] = ""
os.environ["ORCH_SUPABASE_URL"] = ""
os.environ["ORCH_SUPABASE_KEY"] = ""

import rollback_chain


def test_detect_regression_returns_dict_with_regression_key():
    """detect_regression should return a dict with 'regression' key (safe default when disabled)."""
    result = rollback_chain.detect_regression("proj-1", "/tmp", "echo test")
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "regression" in result, "Missing 'regression' key"
    assert result["regression"] is False, "Should be False when disabled"
    assert "failing_tests" in result
    assert "since_commit" in result


def test_stats_returns_dict():
    """stats should return a dict with 'enabled' key."""
    result = rollback_chain.stats()
    assert isinstance(result, dict)
    assert "enabled" in result
    assert result["enabled"] is False, "Should be False per env var"


def test_disabled_mode_returns_safe_defaults():
    """All functions should return safe defaults when disabled."""
    # detect_regression
    dr = rollback_chain.detect_regression("proj-1", "/tmp", "true")
    assert dr["regression"] is False

    # bisect_cause returns None when disabled
    bc = rollback_chain.bisect_cause("/tmp", "abc123", "def456", "true")
    assert bc is None

    # auto_revert returns not-reverted when disabled
    ar = rollback_chain.auto_revert("/tmp", "abc123")
    assert isinstance(ar, dict)
    assert ar["reverted"] is False

    # requeue_with_context returns not-requeued when disabled (no db)
    rq = rollback_chain.requeue_with_context("slug-1", "abc123", ["test_foo"], "proj-1")
    assert isinstance(rq, dict)
    assert rq["requeued"] is False


def test_chain_status_returns_dict():
    """chain_status should return a dict with expected keys."""
    result = rollback_chain.chain_status("proj-1")
    assert isinstance(result, dict)
    assert "pending_rollbacks" in result
    assert "completed" in result
