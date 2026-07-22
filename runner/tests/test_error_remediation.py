#!/usr/bin/env python3
"""Tests for error_remediation module."""
import os, sys, time, threading
import pytest

# Ensure runner dir is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub out db module before importing error_remediation
sys.modules.setdefault("db", type(sys)("db"))

import error_remediation as er


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Reset module state and enable the feature flag for each test."""
    monkeypatch.setenv("ORCH_ERROR_REMEDIATION_ENABLED", "true")
    monkeypatch.setenv("ORCH_ERROR_THRESHOLD", "3")
    monkeypatch.setenv("ORCH_ERROR_WINDOW_S", "300")
    monkeypatch.setenv("ORCH_ROLLBACK_COOLDOWN_S", "600")
    with er._lock:
        er._error_log.clear()
        er._rollbacks.clear()
        er._classify_counts.update({k: 0 for k in er._classify_counts})
        er._remediation_calls = 0
        er._rollback_count = 0
    # Re-read env-based config
    er.ERROR_THRESHOLD = int(os.environ.get("ORCH_ERROR_THRESHOLD", "5"))
    er.ERROR_WINDOW_S = int(os.environ.get("ORCH_ERROR_WINDOW_S", "300"))
    er.ROLLBACK_COOLDOWN = int(os.environ.get("ORCH_ROLLBACK_COOLDOWN_S", "600"))
    yield
    # Cleanup any env vars set by rollback_config
    for key in list(os.environ):
        if key.startswith("ORCH_") and key.endswith("_ENABLED") and key != "ORCH_ERROR_REMEDIATION_ENABLED":
            os.environ.pop(key, None)


# ── 1. Classification tests ─────────────────────────────────────────────────

def test_classify_transient():
    assert er.classify_error("Connection timed out after 30s") == "transient"
    assert er.classify_error("HTTP 429 rate limit exceeded") == "transient"
    assert er.classify_error("503 Service Unavailable") == "transient"


def test_classify_config():
    assert er.classify_error("missing env var ORCH_DB_URL") == "config"
    assert er.classify_error("permission denied: /etc/shadow") == "config"
    assert er.classify_error("ORCH_FOO not set") == "config"


def test_classify_dependency():
    assert er.classify_error("ModuleNotFoundError: No module named 'foo'") == "dependency"
    assert er.classify_error("bash: jq: command not found") == "dependency"


def test_classify_code():
    assert er.classify_error("TypeError: 'NoneType' has no attribute 'x'") == "code"
    assert er.classify_error("SyntaxError: invalid syntax") == "code"


def test_classify_unknown():
    assert er.classify_error("something went wrong somehow") == "unknown"
    assert er.classify_error("") == "unknown"


# ── 2. Threshold triggering ─────────────────────────────────────────────────

def test_threshold_triggers_rollback():
    """When errors exceed threshold, rollback should fire."""
    er.ERROR_THRESHOLD = 3
    for _ in range(3):
        er.record_error("broken_mod", "timeout connecting to DB")
    result = er.maybe_trigger_remediation()
    assert result["action"] == "rollback"
    assert "broken_mod" in result["modules"]
    assert os.environ.get("ORCH_BROKEN_MOD_ENABLED") == "false"


def test_below_threshold_no_rollback():
    """Below threshold, no rollback should happen."""
    er.ERROR_THRESHOLD = 5
    er.record_error("ok_mod", "timeout")
    er.record_error("ok_mod", "timeout")
    result = er.maybe_trigger_remediation()
    assert result["action"] == "none"
    assert os.environ.get("ORCH_OK_MOD_ENABLED") is None


# ── 3. Config rollback ──────────────────────────────────────────────────────

def test_rollback_config_sets_env():
    """rollback_config should set the env var and record the rollback."""
    assert er.rollback_config("my_module", reason="test reason") is True
    assert os.environ.get("ORCH_MY_MODULE_ENABLED") == "false"
    status = er.remediation_status()
    assert "my_module" in status["rolled_back_modules"]


def test_rollback_cooldown():
    """Second rollback within cooldown should be skipped."""
    er.ROLLBACK_COOLDOWN = 9999
    assert er.rollback_config("cool_mod") is True
    assert er.rollback_config("cool_mod") is False  # cooldown


# ── 4. Feature flag ─────────────────────────────────────────────────────────

def test_feature_flag_disabled(monkeypatch):
    """When feature flag is off, rollback and remediation are no-ops."""
    monkeypatch.setenv("ORCH_ERROR_REMEDIATION_ENABLED", "false")
    assert er.rollback_config("any_mod") is False
    for _ in range(10):
        er.record_error("any_mod", "crash")
    result = er.maybe_trigger_remediation()
    assert result["action"] == "disabled"


# ── 5. Stats output ─────────────────────────────────────────────────────────

def test_stats_output():
    """stats() should return comprehensive module statistics."""
    er.record_error("mod_a", "timeout")
    er.record_error("mod_a", "SyntaxError: bad")
    er.record_error("mod_b", "something weird")
    s = er.stats()
    assert s["enabled"] is True
    assert s["errors_in_window"] == 3
    assert s["classifications"]["transient"] >= 1
    assert s["classifications"]["code"] >= 1
    assert s["classifications"]["unknown"] >= 1
    assert isinstance(s["rollbacks"], dict)
    assert isinstance(s["remediation_calls"], int)


def test_remediation_status():
    """remediation_status() should reflect current state."""
    status = er.remediation_status()
    assert "enabled" in status
    assert "active_errors" in status
    assert "rolled_back_modules" in status
    assert status["error_threshold"] == er.ERROR_THRESHOLD
