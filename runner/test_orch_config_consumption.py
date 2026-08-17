#!/usr/bin/env python3
"""Tests for orchestrator config consumption from fleet_config database table.

Validates that runner.py loads configuration at startup via fleet_control.load_config()
and that get_config() falls back gracefully when keys are missing or invalid.

Pattern: branch_lease.py's fail-soft RPC design — errors are logged, not raised.
"""

import os
import sys
import tempfile
from unittest import mock
from typing import Dict, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable external dependencies for testing
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")


def test_orch_config_consumption_startup():
    """Runner loads ORCH_* prefixed keys from fleet_config at startup."""
    try:
        import fleet_control

        # Mock the database to return test config
        with mock.patch("fleet_control.db.select") as mock_select:
            mock_select.return_value = [
                {"key": "ORCH_MAX_PARALLEL", "value": "20"},
                {"key": "ORCH_POLL_SECONDS", "value": "10"},
                {"key": "ORCH_SEM_MAX", "value": "64"},
            ]

            # Clear any existing env vars
            for key in ["ORCH_MAX_PARALLEL", "ORCH_POLL_SECONDS", "ORCH_SEM_MAX"]:
                os.environ.pop(key, None)

            # Call load_config
            loaded = fleet_control.load_config()

            # Verify keys were loaded
            assert loaded == 3, f"Expected 3 keys loaded, got {loaded}"
            assert os.environ.get("ORCH_MAX_PARALLEL") == "20"
            assert os.environ.get("ORCH_POLL_SECONDS") == "10"
            assert os.environ.get("ORCH_SEM_MAX") == "64"
    except AssertionError:
        raise
    except Exception as e:
        raise AssertionError(f"test_orch_config_consumption_startup failed: {e}")


def test_orch_config_consumption_missing_key():
    """Missing config keys gracefully degrade to defaults (fail-soft)."""
    try:
        import fleet_control

        # Ensure key doesn't exist in env
        os.environ.pop("ORCH_NONEXISTENT", None)

        # get_config should return default
        value = fleet_control.get_config("NONEXISTENT", default="default_value")
        assert value == "default_value", f"Expected 'default_value', got '{value}'"
    except AssertionError:
        raise
    except Exception as e:
        raise AssertionError(f"test_orch_config_consumption_missing_key failed: {e}")


def test_orch_config_consumption_get_config_reads_env():
    """get_config() reads from os.environ when fleet_config has been loaded."""
    try:
        import fleet_control

        # Simulate a key that was loaded via load_config
        os.environ["ORCH_TEST_KEY"] = "test_value"

        try:
            value = fleet_control.get_config("TEST_KEY")
            assert value == "test_value", f"Expected 'test_value', got '{value}'"
        finally:
            del os.environ["ORCH_TEST_KEY"]
    except AssertionError:
        raise
    except Exception as e:
        raise AssertionError(f"test_orch_config_consumption_get_config_reads_env failed: {e}")


def test_orch_config_consumption_whitespace_stripped():
    """Config values have whitespace stripped."""
    try:
        import fleet_control

        os.environ["ORCH_PADDED"] = "  value_with_spaces  "

        try:
            value = fleet_control.get_config("PADDED")
            assert value == "value_with_spaces", f"Expected 'value_with_spaces', got '{value}'"
        finally:
            del os.environ["ORCH_PADDED"]
    except AssertionError:
        raise
    except Exception as e:
        raise AssertionError(f"test_orch_config_consumption_whitespace_stripped failed: {e}")


def test_orch_config_consumption_empty_value_uses_default():
    """Empty config values use default (fail-soft)."""
    try:
        import fleet_control

        os.environ["ORCH_EMPTY"] = "   "

        try:
            value = fleet_control.get_config("EMPTY", default="fallback")
            assert value == "fallback", f"Expected 'fallback', got '{value}'"
        finally:
            del os.environ["ORCH_EMPTY"]
    except AssertionError:
        raise
    except Exception as e:
        raise AssertionError(f"test_orch_config_consumption_empty_value_uses_default failed: {e}")


def test_orch_config_consumption_invalid_key_returns_default():
    """Invalid keys (None, non-string) return default (fail-soft)."""
    try:
        import fleet_control

        assert fleet_control.get_config(None, "default") == "default"
        assert fleet_control.get_config("", "default") == "default"
        assert fleet_control.get_config(123, "default") == "default"
    except AssertionError:
        raise
    except Exception as e:
        raise AssertionError(f"test_orch_config_consumption_invalid_key_returns_default failed: {e}")


def test_orch_config_consumption_no_secrets_in_config():
    """Configuration loading rejects keys with credential markers (security)."""
    try:
        import fleet_control

        # Mock database with secret keys (should be filtered)
        with mock.patch("fleet_control.db.select") as mock_select:
            mock_select.return_value = [
                {"key": "ORCH_MAX_PARALLEL", "value": "20"},
                {"key": "ORCH_SECRET_KEY", "value": "should-be-rejected"},
                {"key": "ORCH_TOKEN", "value": "should-be-rejected"},
            ]

            for key in ["ORCH_MAX_PARALLEL", "ORCH_SECRET_KEY", "ORCH_TOKEN"]:
                os.environ.pop(key, None)

            # load_config should only load safe keys
            loaded = fleet_control.load_config()

            # Only ORCH_MAX_PARALLEL should be loaded
            assert os.environ.get("ORCH_MAX_PARALLEL") == "20"
            assert os.environ.get("ORCH_SECRET_KEY") is None
            assert os.environ.get("ORCH_TOKEN") is None
    except AssertionError:
        raise
    except Exception as e:
        raise AssertionError(f"test_orch_config_consumption_no_secrets_in_config failed: {e}")


def test_orch_config_consumption_load_config_returns_count():
    """load_config() returns the count of keys loaded (for diagnostics)."""
    try:
        import fleet_control

        with mock.patch("fleet_control.db.select") as mock_select:
            mock_select.return_value = [
                {"key": "ORCH_PARAM1", "value": "val1"},
                {"key": "ORCH_PARAM2", "value": "val2"},
                {"key": "ORCH_PARAM3", "value": "val3"},
            ]

            for key in ["ORCH_PARAM1", "ORCH_PARAM2", "ORCH_PARAM3"]:
                os.environ.pop(key, None)

            count = fleet_control.load_config()
            assert count == 3, f"Expected count 3, got {count}"
    except AssertionError:
        raise
    except Exception as e:
        raise AssertionError(f"test_orch_config_consumption_load_config_returns_count failed: {e}")


def test_orch_config_consumption_handles_db_errors():
    """Configuration loading fails gracefully on database errors (fail-soft)."""
    try:
        import fleet_control

        with mock.patch("fleet_control.db.select") as mock_select:
            # Simulate database error
            mock_select.side_effect = RuntimeError("Database connection failed")

            # Should not raise, should return 0
            count = fleet_control.load_config()
            assert count == 0, f"Expected 0 on error, got {count}"
    except AssertionError:
        raise
    except Exception as e:
        raise AssertionError(f"test_orch_config_consumption_handles_db_errors failed: {e}")


def test_orch_config_consumption_multiple_calls_idempotent():
    """Multiple calls to load_config() are safe (idempotent)."""
    try:
        import fleet_control

        with mock.patch("fleet_control.db.select") as mock_select:
            mock_select.return_value = [
                {"key": "ORCH_PARAM1", "value": "value1"},
            ]

            os.environ.pop("ORCH_PARAM1", None)

            # First call
            count1 = fleet_control.load_config()
            assert count1 == 1
            assert os.environ.get("ORCH_PARAM1") == "value1"

            # Second call should also work
            count2 = fleet_control.load_config()
            assert count2 == 1
            assert os.environ.get("ORCH_PARAM1") == "value1"
    except AssertionError:
        raise
    except Exception as e:
        raise AssertionError(f"test_orch_config_consumption_multiple_calls_idempotent failed: {e}")


if __name__ == "__main__":
    """Run all tests and report results."""
    test_functions = [
        test_orch_config_consumption_startup,
        test_orch_config_consumption_missing_key,
        test_orch_config_consumption_get_config_reads_env,
        test_orch_config_consumption_whitespace_stripped,
        test_orch_config_consumption_empty_value_uses_default,
        test_orch_config_consumption_invalid_key_returns_default,
        test_orch_config_consumption_no_secrets_in_config,
        test_orch_config_consumption_load_config_returns_count,
        test_orch_config_consumption_handles_db_errors,
        test_orch_config_consumption_multiple_calls_idempotent,
    ]

    passed = 0
    failed = 0
    for test_fn in test_functions:
        try:
            test_fn()
            passed += 1
            print(f"✓ {test_fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"✗ {test_fn.__name__}: {e}")

    print(f"\n{passed}/{len(test_functions)} tests passed")
    sys.exit(0 if failed == 0 else 1)
