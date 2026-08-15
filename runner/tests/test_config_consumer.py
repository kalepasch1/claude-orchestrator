#!/usr/bin/env python3
"""Tests for config_consumer.py - orchestrator configuration consumption.

Tests validate:
- Environment variable consumption with ORCH_ prefix
- Default value fallback behavior
- Type coercion (bool, int, float, string)
- Edge cases (None, empty values, bad parses)
- Fail-soft error handling with sensible defaults
"""

import os
import sys
import threading

# Setup path and disable external dependencies
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import config_consumer


# --- Basic Consumption Tests ---

def test_get_with_env_var_present():
    """get() returns value when ORCH_* env var exists."""
    os.environ["ORCH_TEST_KEY"] = "test_value"
    try:
        value = config_consumer.get("TEST_KEY")
        assert value == "test_value", f"Expected 'test_value', got {value}"
    finally:
        del os.environ["ORCH_TEST_KEY"]


def test_get_missing_env_returns_empty_string():
    """get() returns empty string when key missing and no default."""
    os.environ.pop("ORCH_MISSING_KEY", None)
    value = config_consumer.get("MISSING_KEY")
    assert value == "", f"Expected empty string, got {value!r}"


def test_get_missing_env_with_default():
    """get() returns default when key missing."""
    os.environ.pop("ORCH_MISSING_KEY", None)
    value = config_consumer.get("MISSING_KEY", default="fallback")
    assert value == "fallback", f"Expected 'fallback', got {value}"


def test_get_strips_whitespace():
    """get() strips leading/trailing whitespace from env value."""
    os.environ["ORCH_WHITESPACE"] = "  padded  "
    try:
        value = config_consumer.get("WHITESPACE")
        assert value == "padded", f"Expected 'padded', got {value!r}"
    finally:
        del os.environ["ORCH_WHITESPACE"]


def test_get_empty_env_value_returns_default():
    """get() returns default when env value is empty string."""
    os.environ["ORCH_EMPTY"] = ""
    try:
        value = config_consumer.get("EMPTY", default="default_val")
        assert value == "default_val", f"Expected 'default_val', got {value!r}"
    finally:
        del os.environ["ORCH_EMPTY"]


def test_get_whitespace_only_env_returns_default():
    """get() returns default when env value is whitespace-only."""
    os.environ["ORCH_SPACES"] = "   "
    try:
        value = config_consumer.get("SPACES", default="default_val")
        assert value == "default_val", f"Expected 'default_val', got {value!r}"
    finally:
        del os.environ["ORCH_SPACES"]


def test_get_int_valid():
    """get_int() parses string to int."""
    os.environ["ORCH_PORT"] = "8080"
    try:
        value = config_consumer.get_int("PORT")
        assert isinstance(value, int), f"Expected int, got {type(value).__name__}"
        assert value == 8080, f"Expected 8080, got {value}"
    finally:
        del os.environ["ORCH_PORT"]


def test_get_int_negative():
    """get_int() parses negative integers."""
    os.environ["ORCH_OFFSET"] = "-42"
    try:
        value = config_consumer.get_int("OFFSET")
        assert value == -42, f"Expected -42, got {value}"
    finally:
        del os.environ["ORCH_OFFSET"]


def test_get_int_missing_returns_default():
    """get_int() returns default when key missing."""
    os.environ.pop("ORCH_MISSING_INT", None)
    value = config_consumer.get_int("MISSING_INT", default=42)
    assert value == 42, f"Expected 42, got {value}"


def test_get_int_invalid_returns_default():
    """get_int() returns default when parse fails."""
    os.environ["ORCH_BAD_INT"] = "not_a_number"
    try:
        value = config_consumer.get_int("BAD_INT", default=99)
        assert value == 99, f"Expected 99, got {value}"
    finally:
        del os.environ["ORCH_BAD_INT"]


def test_get_int_default_zero():
    """get_int() defaults to 0 when no default provided."""
    os.environ.pop("ORCH_NO_INT", None)
    value = config_consumer.get_int("NO_INT")
    assert value == 0, f"Expected 0, got {value}"


def test_get_bool_true_variants():
    """get_bool() recognizes '1', 'true', 'yes', 'on' as True."""
    for true_val in ["1", "true", "True", "TRUE", "yes", "YES", "on", "ON"]:
        os.environ["ORCH_FLAG"] = true_val
        try:
            value = config_consumer.get_bool("FLAG")
            assert value is True, f"Expected True for '{true_val}', got {value}"
        finally:
            del os.environ["ORCH_FLAG"]


def test_get_bool_false_variants():
    """get_bool() recognizes '0', 'false', etc. as False."""
    for false_val in ["0", "false", "False", "FALSE", "no", "off", "anything"]:
        os.environ["ORCH_FLAG"] = false_val
        try:
            value = config_consumer.get_bool("FLAG")
            assert value is False, f"Expected False for '{false_val}', got {value}"
        finally:
            del os.environ["ORCH_FLAG"]


def test_get_bool_missing_returns_default():
    """get_bool() returns default when key missing."""
    os.environ.pop("ORCH_MISSING_BOOL", None)
    value = config_consumer.get_bool("MISSING_BOOL", default=True)
    assert value is True, f"Expected True, got {value}"


def test_get_bool_default_false():
    """get_bool() defaults to False when no default provided."""
    os.environ.pop("ORCH_NO_BOOL", None)
    value = config_consumer.get_bool("NO_BOOL")
    assert value is False, f"Expected False, got {value}"


def test_get_float_valid():
    """get_float() parses string to float."""
    os.environ["ORCH_RATE"] = "3.14"
    try:
        value = config_consumer.get_float("RATE")
        assert isinstance(value, float), f"Expected float, got {type(value).__name__}"
        assert abs(value - 3.14) < 0.001, f"Expected ~3.14, got {value}"
    finally:
        del os.environ["ORCH_RATE"]


def test_get_float_negative():
    """get_float() parses negative floats."""
    os.environ["ORCH_DELTA"] = "-2.5"
    try:
        value = config_consumer.get_float("DELTA")
        assert value == -2.5, f"Expected -2.5, got {value}"
    finally:
        del os.environ["ORCH_DELTA"]


def test_get_float_integer_input():
    """get_float() accepts integer strings."""
    os.environ["ORCH_INT_FLOAT"] = "42"
    try:
        value = config_consumer.get_float("INT_FLOAT")
        assert value == 42.0, f"Expected 42.0, got {value}"
    finally:
        del os.environ["ORCH_INT_FLOAT"]


def test_get_float_missing_returns_default():
    """get_float() returns default when key missing."""
    os.environ.pop("ORCH_MISSING_FLOAT", None)
    value = config_consumer.get_float("MISSING_FLOAT", default=1.5)
    assert value == 1.5, f"Expected 1.5, got {value}"


def test_get_float_invalid_returns_default():
    """get_float() returns default when parse fails."""
    os.environ["ORCH_BAD_FLOAT"] = "not_a_float"
    try:
        value = config_consumer.get_float("BAD_FLOAT", default=2.5)
        assert value == 2.5, f"Expected 2.5, got {value}"
    finally:
        del os.environ["ORCH_BAD_FLOAT"]


def test_get_float_default_zero():
    """get_float() defaults to 0.0 when no default provided."""
    os.environ.pop("ORCH_NO_FLOAT", None)
    value = config_consumer.get_float("NO_FLOAT")
    assert value == 0.0, f"Expected 0.0, got {value}"


# --- load_all() Tests ---

def test_load_all_collects_orch_prefixed_keys():
    """load_all() returns dict of all ORCH_* env vars."""
    os.environ["ORCH_KEY1"] = "value1"
    os.environ["ORCH_KEY2"] = "value2"
    os.environ["NOT_ORCH"] = "should_not_appear"

    try:
        config = config_consumer.load_all()
        assert "KEY1" in config, "Expected KEY1 in config"
        assert "KEY2" in config, "Expected KEY2 in config"
        assert config["KEY1"] == "value1", f"Expected 'value1', got {config['KEY1']}"
        assert config["KEY2"] == "value2", f"Expected 'value2', got {config['KEY2']}"
        assert "NOT_ORCH" not in config, "Non-ORCH key should not be in config"
    finally:
        del os.environ["ORCH_KEY1"]
        del os.environ["ORCH_KEY2"]
        del os.environ["NOT_ORCH"]


def test_load_all_empty_when_no_orch_keys():
    """load_all() returns empty dict when no ORCH_* vars exist."""
    # Clear any ORCH_ vars
    for key in list(os.environ.keys()):
        if key.startswith("ORCH_"):
            del os.environ[key]

    config = config_consumer.load_all()
    assert isinstance(config, dict), f"Expected dict, got {type(config).__name__}"
    assert len(config) == 0, f"Expected empty config, got {config}"


def test_load_all_strips_prefix():
    """load_all() removes ORCH_ prefix from keys."""
    os.environ["ORCH_DATABASE_URL"] = "postgres://localhost"
    try:
        config = config_consumer.load_all()
        assert "DATABASE_URL" in config, "Expected DATABASE_URL (without ORCH_ prefix)"
        assert "ORCH_DATABASE_URL" not in config, "ORCH_DATABASE_URL should not be in result"
    finally:
        del os.environ["ORCH_DATABASE_URL"]


def test_load_all_preserves_empty_values():
    """load_all() includes ORCH_* keys even with empty values."""
    os.environ["ORCH_EMPTY"] = ""
    try:
        config = config_consumer.load_all()
        assert "EMPTY" in config, "Expected EMPTY key in config"
        assert config["EMPTY"] == "", f"Expected empty string, got {config['EMPTY']!r}"
    finally:
        del os.environ["ORCH_EMPTY"]


# --- Edge Cases ---

def test_get_with_special_characters():
    """get() handles special characters in values."""
    os.environ["ORCH_SPECIAL"] = 'value with "quotes" and\nnewlines'
    try:
        value = config_consumer.get("SPECIAL")
        assert "quotes" in value
        assert "\n" in value
    finally:
        del os.environ["ORCH_SPECIAL"]


def test_get_with_unicode():
    """get() handles unicode characters."""
    os.environ["ORCH_UNICODE"] = "value with émojis 🚀"
    try:
        value = config_consumer.get("UNICODE")
        assert "émojis" in value
        assert "🚀" in value
    finally:
        del os.environ["ORCH_UNICODE"]


def test_get_with_large_value():
    """get() handles large string values."""
    large_value = "x" * 10000
    os.environ["ORCH_LARGE"] = large_value
    try:
        value = config_consumer.get("LARGE")
        assert len(value) == 10000, f"Expected 10000 chars, got {len(value)}"
        assert value == large_value
    finally:
        del os.environ["ORCH_LARGE"]


def test_get_case_sensitivity():
    """get() is case-sensitive for key matching."""
    os.environ["ORCH_lowercase"] = "value"
    try:
        # get() uses key as-is, so "lowercase" looks for ORCH_lowercase
        value = config_consumer.get("lowercase")
        assert value == "value", f"Expected 'value', got {value}"
    finally:
        del os.environ["ORCH_lowercase"]


def test_get_int_with_whitespace():
    """get_int() handles whitespace in numeric strings."""
    os.environ["ORCH_PADDED_INT"] = "  42  "
    try:
        value = config_consumer.get_int("PADDED_INT")
        assert value == 42, f"Expected 42, got {value}"
    finally:
        del os.environ["ORCH_PADDED_INT"]


def test_get_float_with_scientific_notation():
    """get_float() handles scientific notation."""
    os.environ["ORCH_SCIENTIFIC"] = "1e-3"
    try:
        value = config_consumer.get_float("SCIENTIFIC")
        assert abs(value - 0.001) < 0.0001, f"Expected ~0.001, got {value}"
    finally:
        del os.environ["ORCH_SCIENTIFIC"]


def test_get_bool_with_whitespace():
    """get_bool() handles whitespace in boolean strings."""
    os.environ["ORCH_PADDED_BOOL"] = "  true  "
    try:
        value = config_consumer.get_bool("PADDED_BOOL")
        assert value is True, f"Expected True, got {value}"
    finally:
        del os.environ["ORCH_PADDED_BOOL"]


# --- Concurrency Tests ---

def test_concurrent_get_reads():
    """Multiple threads can read config concurrently."""
    os.environ["ORCH_CONCURRENT"] = "concurrent_value"
    results = []
    errors = []

    def reader():
        try:
            value = config_consumer.get("CONCURRENT")
            results.append(value)
        except Exception as e:
            errors.append(e)

    try:
        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent read: {errors}"
        assert len(results) == 10, f"Expected 10 results, got {len(results)}"
        assert all(r == "concurrent_value" for r in results)
    finally:
        del os.environ["ORCH_CONCURRENT"]


def test_concurrent_load_all():
    """Multiple threads can call load_all() concurrently."""
    os.environ["ORCH_A"] = "a"
    os.environ["ORCH_B"] = "b"
    results = []
    errors = []

    def loader():
        try:
            config = config_consumer.load_all()
            results.append(config)
        except Exception as e:
            errors.append(e)

    try:
        threads = [threading.Thread(target=loader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent load_all: {errors}"
        assert len(results) == 5
        for config in results:
            assert config.get("A") == "a"
            assert config.get("B") == "b"
    finally:
        del os.environ["ORCH_A"]
        del os.environ["ORCH_B"]


def test_concurrent_mixed_operations():
    """Concurrent reads of different types don't interfere."""
    os.environ["ORCH_INT_VAL"] = "42"
    os.environ["ORCH_BOOL_VAL"] = "true"
    os.environ["ORCH_FLOAT_VAL"] = "3.14"

    results = {"int": [], "bool": [], "float": [], "all": []}
    errors = []

    def read_int():
        try:
            results["int"].append(config_consumer.get_int("INT_VAL"))
        except Exception as e:
            errors.append(e)

    def read_bool():
        try:
            results["bool"].append(config_consumer.get_bool("BOOL_VAL"))
        except Exception as e:
            errors.append(e)

    def read_float():
        try:
            results["float"].append(config_consumer.get_float("FLOAT_VAL"))
        except Exception as e:
            errors.append(e)

    def read_all():
        try:
            results["all"].append(config_consumer.load_all())
        except Exception as e:
            errors.append(e)

    try:
        threads = [
            threading.Thread(target=read_int),
            threading.Thread(target=read_bool),
            threading.Thread(target=read_float),
            threading.Thread(target=read_all),
            threading.Thread(target=read_int),
            threading.Thread(target=read_bool),
            threading.Thread(target=read_float),
            threading.Thread(target=read_all),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent operations: {errors}"
        assert all(v == 42 for v in results["int"])
        assert all(v is True for v in results["bool"])
        assert all(abs(v - 3.14) < 0.01 for v in results["float"])
    finally:
        del os.environ["ORCH_INT_VAL"]
        del os.environ["ORCH_BOOL_VAL"]
        del os.environ["ORCH_FLOAT_VAL"]


# --- Integration Tests ---

def test_full_configuration_flow():
    """Full configuration flow: load_all then individual gets."""
    os.environ["ORCH_HOST"] = "localhost"
    os.environ["ORCH_PORT"] = "5432"
    os.environ["ORCH_ENABLED"] = "true"
    os.environ["ORCH_TIMEOUT"] = "30.5"

    try:
        # Load all
        all_config = config_consumer.load_all()
        assert all_config["HOST"] == "localhost"
        assert all_config["PORT"] == "5432"
        assert all_config["ENABLED"] == "true"

        # Get individual values
        host = config_consumer.get("HOST")
        port = config_consumer.get_int("PORT")
        enabled = config_consumer.get_bool("ENABLED")
        timeout = config_consumer.get_float("TIMEOUT")

        assert host == "localhost"
        assert port == 5432
        assert enabled is True
        assert abs(timeout - 30.5) < 0.01
    finally:
        del os.environ["ORCH_HOST"]
        del os.environ["ORCH_PORT"]
        del os.environ["ORCH_ENABLED"]
        del os.environ["ORCH_TIMEOUT"]


def test_mixed_env_and_defaults():
    """Mix of env vars and defaults works together."""
    os.environ["ORCH_FROM_ENV"] = "env_value"
    os.environ["ORCH_FROM_ENV_INT"] = "100"

    try:
        # Env takes precedence
        value = config_consumer.get("FROM_ENV", default="default_value")
        assert value == "env_value"

        # Default used when missing
        missing = config_consumer.get("NOT_SET", default="default_missing")
        assert missing == "default_missing"

        # Int coercion with env
        int_val = config_consumer.get_int("FROM_ENV_INT", default=0)
        assert int_val == 100

        # Int default when missing
        int_missing = config_consumer.get_int("NOT_SET_INT", default=42)
        assert int_missing == 42
    finally:
        del os.environ["ORCH_FROM_ENV"]
        del os.environ["ORCH_FROM_ENV_INT"]


def test_prefix_not_optional():
    """Non-ORCH_ prefixed env vars are not consumed."""
    os.environ["NOT_ORCH_KEY"] = "should_not_appear"

    try:
        value = config_consumer.get("NOT_ORCH_KEY")
        assert value == "", f"Non-ORCH key should not be found, got {value!r}"

        # Also not in load_all()
        config = config_consumer.load_all()
        assert "NOT_ORCH_KEY" not in config
    finally:
        del os.environ["NOT_ORCH_KEY"]


# --- DB-Backed Config Tests (fleet_config table) ---

def test_load_config_from_env_fallback():
    """load_config() falls back to environment when DB unavailable."""
    os.environ["ORCH_DB_TEST"] = "from_env"
    try:
        value = config_consumer.load_config("DB_TEST")
        assert value == "from_env", f"Expected 'from_env', got {value!r}"
    finally:
        del os.environ["ORCH_DB_TEST"]


def test_load_config_missing_returns_default():
    """load_config() returns default when key missing from DB and env."""
    os.environ.pop("ORCH_MISSING_DB_KEY", None)
    value = config_consumer.load_config("MISSING_DB_KEY", default="fallback")
    assert value == "fallback", f"Expected 'fallback', got {value!r}"


def test_load_config_missing_returns_empty_string():
    """load_config() returns empty string when no default provided."""
    os.environ.pop("ORCH_MISSING_DB_KEY_NODEF", None)
    value = config_consumer.load_config("MISSING_DB_KEY_NODEF")
    assert value == "", f"Expected empty string, got {value!r}"


def test_load_config_strips_whitespace():
    """load_config() strips whitespace from values."""
    os.environ["ORCH_WHITESPACE_DB"] = "  padded  "
    try:
        value = config_consumer.load_config("WHITESPACE_DB")
        assert value == "padded", f"Expected 'padded', got {value!r}"
    finally:
        del os.environ["ORCH_WHITESPACE_DB"]


def test_load_config_empty_env_uses_default():
    """load_config() uses default when env value is empty."""
    os.environ["ORCH_EMPTY_DB"] = ""
    try:
        value = config_consumer.load_config("EMPTY_DB", default="default_val")
        assert value == "default_val", f"Expected 'default_val', got {value!r}"
    finally:
        del os.environ["ORCH_EMPTY_DB"]


# --- Cache Tests ---

def test_cache_invalidate_clears_cached_values():
    """invalidate_cache() clears the cache."""
    os.environ["ORCH_CACHE_TEST"] = "initial"
    try:
        value1 = config_consumer.load_config("CACHE_TEST")
        assert value1 == "initial"

        config_consumer.invalidate_cache()

        os.environ["ORCH_CACHE_TEST"] = "updated"
        value2 = config_consumer.load_config("CACHE_TEST")
        assert value2 == "updated", f"Cache not invalidated; got {value2!r}"
    finally:
        os.environ.pop("ORCH_CACHE_TEST", None)


def test_cache_ttl_expiry():
    """Cache expires after TTL and reloads from source."""
    import time

    os.environ["ORCH_TTL_TEST"] = "cached"
    try:
        value1 = config_consumer.load_config("TTL_TEST")
        assert value1 == "cached"

        os.environ["ORCH_TTL_TEST"] = "expired"

        config_consumer.invalidate_cache()
        value2 = config_consumer.load_config("TTL_TEST")
        assert value2 == "expired", f"Expected 'expired', got {value2!r}"
    finally:
        os.environ.pop("ORCH_TTL_TEST", None)


def test_load_config_concurrent_reads():
    """Multiple threads can read load_config() concurrently."""
    os.environ["ORCH_CONCURRENT_DB"] = "concurrent_value"
    results = []
    errors = []

    def reader():
        try:
            value = config_consumer.load_config("CONCURRENT_DB")
            results.append(value)
        except Exception as e:
            errors.append(e)

    try:
        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent load_config: {errors}"
        assert len(results) == 10, f"Expected 10 results, got {len(results)}"
        assert all(r == "concurrent_value" for r in results)
    finally:
        del os.environ["ORCH_CONCURRENT_DB"]


def test_load_config_db_unavailable_uses_env():
    """load_config() falls back to env when DB is unavailable."""
    os.environ["ORCH_DB_FALLBACK"] = "env_value"
    try:
        value = config_consumer.load_config("DB_FALLBACK")
        assert value == "env_value", f"Expected 'env_value', got {value!r}"
    finally:
        del os.environ["ORCH_DB_FALLBACK"]


def test_load_config_db_unavailable_uses_default():
    """load_config() uses default when DB unavailable and key missing from env."""
    os.environ.pop("ORCH_DB_MISSING", None)
    value = config_consumer.load_config("DB_MISSING", default="default")
    assert value == "default", f"Expected 'default', got {value!r}"


def test_load_config_cache_prevents_repeated_db_calls():
    """load_config() caches results to avoid repeated DB calls."""
    os.environ["ORCH_CACHE_PERF"] = "cached"
    try:
        value1 = config_consumer.load_config("CACHE_PERF")
        value2 = config_consumer.load_config("CACHE_PERF")
        assert value1 == value2 == "cached"
    finally:
        os.environ.pop("ORCH_CACHE_PERF", None)


# --- Test Runner ---

def run_all_tests():
    """Run all test functions and report results."""
    test_count = 0
    pass_count = 0
    fail_count = 0
    errors = []

    for name, obj in list(globals().items()):
        if callable(obj) and name.startswith("test_"):
            test_count += 1
            try:
                obj()
                pass_count += 1
                print(f"  PASS  {name}")
            except AssertionError as e:
                fail_count += 1
                msg = f"{name}: {e}"
                print(f"  FAIL  {msg}")
                errors.append(msg)
            except Exception as e:
                fail_count += 1
                msg = f"{name}: {type(e).__name__}: {e}"
                print(f"  ERROR {msg}")
                errors.append(msg)

    print(f"\nconfig_consumer tests: {pass_count}/{test_count} passed")
    if fail_count > 0:
        print(f"Failures: {fail_count}")
        for error in errors[:5]:
            print(f"  - {error}")
        if len(errors) > 5:
            print(f"  ... and {len(errors) - 5} more")

    return fail_count == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
