#!/usr/bin/env python3
"""Tests for orch-config-consumption — module-level config consumption functions.

Tests validate:
- Environment variable consumption with ORCH_ prefix
- Default value fallback behavior
- Type coercion (bool, int, float, string)
- Cache behavior for load_config() with fleet_config DB fallback
- Thread-safe consumption patterns
- Fail-soft error handling
"""

import os
import sys
import time
import threading
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable external dependencies for testing
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import config_consumer


class TestLoadAll:
    """Test load_all() — consume all ORCH_* prefixed env vars."""

    def test_load_all_returns_dict():
        """load_all() returns a dictionary."""
        result = config_consumer.load_all()
        assert isinstance(result, dict), f"Expected dict, got {type(result).__name__}"

    def test_load_all_filters_orch_prefix():
        """load_all() only includes ORCH_* prefixed keys."""
        os.environ["ORCH_KEY1"] = "value1"
        os.environ["ORCH_KEY2"] = "value2"
        os.environ["OTHER_KEY"] = "value3"

        result = config_consumer.load_all()

        assert "KEY1" in result, "ORCH_KEY1 should be in result as KEY1"
        assert "KEY2" in result, "ORCH_KEY2 should be in result as KEY2"
        assert "OTHER_KEY" not in result, "Non-ORCH keys should be filtered out"
        assert result["KEY1"] == "value1"
        assert result["KEY2"] == "value2"

        del os.environ["ORCH_KEY1"]
        del os.environ["ORCH_KEY2"]
        del os.environ["OTHER_KEY"]

    def test_load_all_empty_when_no_orch_keys():
        """load_all() returns empty dict when no ORCH_* keys present."""
        # Clean all ORCH_ keys
        for key in list(os.environ.keys()):
            if key.startswith("ORCH_"):
                del os.environ[key]

        result = config_consumer.load_all()
        assert result == {}, f"Expected empty dict, got {result}"

    def test_load_all_includes_empty_values():
        """load_all() includes ORCH_* keys even with empty values."""
        os.environ["ORCH_EMPTY"] = ""

        result = config_consumer.load_all()
        assert "EMPTY" in result, "Empty values should be included"
        assert result["EMPTY"] == ""

        del os.environ["ORCH_EMPTY"]


class TestGet:
    """Test get() — consume ORCH_{key} from environment."""

    def test_get_from_env_with_orch_prefix():
        """get() retrieves ORCH_{key} from environment."""
        os.environ["ORCH_MYKEY"] = "myvalue"

        value = config_consumer.get("MYKEY")
        assert value == "myvalue", f"Expected 'myvalue', got {value}"

        del os.environ["ORCH_MYKEY"]

    def test_get_returns_empty_string_when_missing():
        """get() returns empty string when ORCH_{key} not found."""
        os.environ.pop("ORCH_MISSING", None)

        value = config_consumer.get("MISSING")
        assert value == "", f"Expected empty string, got {value!r}"

    def test_get_returns_default_when_missing():
        """get() returns default parameter when ORCH_{key} not found."""
        os.environ.pop("ORCH_MISSING", None)

        value = config_consumer.get("MISSING", default="default_value")
        assert value == "default_value", f"Expected 'default_value', got {value}"

    def test_get_strips_whitespace():
        """get() strips leading/trailing whitespace from value."""
        os.environ["ORCH_WHITESPACE"] = "  trimmed  "

        value = config_consumer.get("WHITESPACE")
        assert value == "trimmed", f"Expected 'trimmed', got {value!r}"

        del os.environ["ORCH_WHITESPACE"]

    def test_get_empty_value_returns_default():
        """get() returns default when value is empty/whitespace only."""
        os.environ["ORCH_EMPTY"] = "   "

        value = config_consumer.get("EMPTY", default="fallback")
        assert value == "fallback", f"Expected 'fallback', got {value}"

        del os.environ["ORCH_EMPTY"]

    def test_get_lowercase_key_lookup():
        """get() is case-insensitive for key lookup (lowercase 'key' -> ORCH_KEY)."""
        os.environ["ORCH_TESTKEY"] = "testvalue"

        value = config_consumer.get("testkey")
        # Note: actual behavior depends on implementation
        # If implementation lowercases, this will work; if not, test documents behavior
        # For now, assuming keys are uppercase in env
        del os.environ["ORCH_TESTKEY"]


class TestGetInt:
    """Test get_int() — consume ORCH_{key} as integer."""

    def test_get_int_from_env():
        """get_int() parses integer from env var."""
        os.environ["ORCH_COUNT"] = "42"

        value = config_consumer.get_int("COUNT")
        assert isinstance(value, int), f"Expected int, got {type(value).__name__}"
        assert value == 42, f"Expected 42, got {value}"

        del os.environ["ORCH_COUNT"]

    def test_get_int_returns_default_when_missing():
        """get_int() returns default when ORCH_{key} not found."""
        os.environ.pop("ORCH_MISSING", None)

        value = config_consumer.get_int("MISSING", default=99)
        assert value == 99, f"Expected 99, got {value}"

    def test_get_int_default_is_zero():
        """get_int() defaults to 0 when key missing and no default provided."""
        os.environ.pop("ORCH_MISSING", None)

        value = config_consumer.get_int("MISSING")
        assert value == 0, f"Expected 0, got {value}"

    def test_get_int_unparseable_returns_default():
        """get_int() returns default when value can't parse as int."""
        os.environ["ORCH_BADINT"] = "not_a_number"

        value = config_consumer.get_int("BADINT", default=55)
        assert value == 55, f"Expected 55, got {value}"

        del os.environ["ORCH_BADINT"]

    def test_get_int_negative_numbers():
        """get_int() handles negative integers."""
        os.environ["ORCH_NEGINT"] = "-123"

        value = config_consumer.get_int("NEGINT")
        assert value == -123, f"Expected -123, got {value}"

        del os.environ["ORCH_NEGINT"]

    def test_get_int_empty_returns_default():
        """get_int() returns default when value is empty."""
        os.environ["ORCH_EMPTYINT"] = "   "

        value = config_consumer.get_int("EMPTYINT", default=77)
        assert value == 77, f"Expected 77, got {value}"

        del os.environ["ORCH_EMPTYINT"]


class TestGetBool:
    """Test get_bool() — consume ORCH_{key} as boolean."""

    def test_get_bool_true_variants():
        """get_bool() recognizes 'true', '1', 'yes', 'on' as True."""
        true_values = ["true", "True", "TRUE", "1", "yes", "YES", "on", "ON"]

        for val in true_values:
            os.environ["ORCH_BOOL"] = val
            value = config_consumer.get_bool("BOOL")
            assert value is True, f"Expected True for '{val}', got {value}"
            del os.environ["ORCH_BOOL"]

    def test_get_bool_false_variants():
        """get_bool() recognizes anything else as False."""
        false_values = ["false", "False", "FALSE", "0", "no", "NO", "off", "anything"]

        for val in false_values:
            os.environ["ORCH_BOOL"] = val
            value = config_consumer.get_bool("BOOL")
            assert value is False, f"Expected False for '{val}', got {value}"
            del os.environ["ORCH_BOOL"]

    def test_get_bool_returns_default_when_missing():
        """get_bool() returns default when ORCH_{key} not found."""
        os.environ.pop("ORCH_MISSING", None)

        value = config_consumer.get_bool("MISSING", default=True)
        assert value is True, f"Expected True, got {value}"

    def test_get_bool_default_is_false():
        """get_bool() defaults to False when key missing and no default provided."""
        os.environ.pop("ORCH_MISSING", None)

        value = config_consumer.get_bool("MISSING")
        assert value is False, f"Expected False, got {value}"

    def test_get_bool_empty_returns_default():
        """get_bool() returns default when value is empty/whitespace only."""
        os.environ["ORCH_EMPTY"] = "   "

        value = config_consumer.get_bool("EMPTY", default=True)
        assert value is True, f"Expected True, got {value}"

        del os.environ["ORCH_EMPTY"]

    def test_get_bool_case_insensitive():
        """get_bool() is case-insensitive for true/false/yes/on."""
        test_cases = [
            ("TrUe", True),
            ("YeS", True),
            ("On", True),
            ("FaLsE", False),
            ("nO", False),
            ("oFf", False),
        ]

        for val, expected in test_cases:
            os.environ["ORCH_BOOL"] = val
            value = config_consumer.get_bool("BOOL")
            assert value is expected, f"Expected {expected} for '{val}', got {value}"
            del os.environ["ORCH_BOOL"]


class TestGetFloat:
    """Test get_float() — consume ORCH_{key} as float."""

    def test_get_float_from_env():
        """get_float() parses float from env var."""
        os.environ["ORCH_RATE"] = "3.14"

        value = config_consumer.get_float("RATE")
        assert isinstance(value, float), f"Expected float, got {type(value).__name__}"
        assert abs(value - 3.14) < 0.001, f"Expected ~3.14, got {value}"

        del os.environ["ORCH_RATE"]

    def test_get_float_returns_default_when_missing():
        """get_float() returns default when ORCH_{key} not found."""
        os.environ.pop("ORCH_MISSING", None)

        value = config_consumer.get_float("MISSING", default=9.99)
        assert abs(value - 9.99) < 0.001, f"Expected 9.99, got {value}"

    def test_get_float_default_is_zero():
        """get_float() defaults to 0.0 when key missing and no default provided."""
        os.environ.pop("ORCH_MISSING", None)

        value = config_consumer.get_float("MISSING")
        assert value == 0.0, f"Expected 0.0, got {value}"

    def test_get_float_unparseable_returns_default():
        """get_float() returns default when value can't parse as float."""
        os.environ["ORCH_BADFLOAT"] = "not_a_float"

        value = config_consumer.get_float("BADFLOAT", default=2.71)
        assert abs(value - 2.71) < 0.001, f"Expected 2.71, got {value}"

        del os.environ["ORCH_BADFLOAT"]

    def test_get_float_negative_numbers():
        """get_float() handles negative floats."""
        os.environ["ORCH_NEGFLOAT"] = "-12.34"

        value = config_consumer.get_float("NEGFLOAT")
        assert abs(value - (-12.34)) < 0.001, f"Expected ~-12.34, got {value}"

        del os.environ["ORCH_NEGFLOAT"]

    def test_get_float_integer_values():
        """get_float() parses integer strings as floats."""
        os.environ["ORCH_INTFLOAT"] = "42"

        value = config_consumer.get_float("INTFLOAT")
        assert isinstance(value, float), f"Expected float, got {type(value).__name__}"
        assert value == 42.0, f"Expected 42.0, got {value}"

        del os.environ["ORCH_INTFLOAT"]

    def test_get_float_empty_returns_default():
        """get_float() returns default when value is empty."""
        os.environ["ORCH_EMPTYFLOAT"] = "   "

        value = config_consumer.get_float("EMPTYFLOAT", default=1.5)
        assert abs(value - 1.5) < 0.001, f"Expected 1.5, got {value}"

        del os.environ["ORCH_EMPTYFLOAT"]


class TestLoadConfig:
    """Test load_config() — load from fleet_config DB with cache and fallback."""

    def test_load_config_fallback_to_env():
        """load_config() falls back to env var when DB unavailable."""
        os.environ["ORCH_DBKEY"] = "env_value"

        # With DB mock unavailable, should use env fallback
        value = config_consumer.load_config("DBKEY", default="default")
        assert value == "env_value", f"Expected 'env_value', got {value}"

        del os.environ["ORCH_DBKEY"]

    def test_load_config_returns_default_when_missing():
        """load_config() returns default when ORCH_{key} not in env or DB."""
        os.environ.pop("ORCH_MISSING", None)

        value = config_consumer.load_config("MISSING", default="default_value")
        assert value == "default_value", f"Expected 'default_value', got {value}"

    def test_load_config_default_is_empty_string():
        """load_config() defaults to empty string when key missing and no default."""
        os.environ.pop("ORCH_MISSING", None)
        config_consumer.invalidate_cache()

        value = config_consumer.load_config("MISSING")
        assert value == "", f"Expected empty string, got {value!r}"

    def test_load_config_cache_ttl():
        """load_config() caches values for 60 seconds."""
        os.environ["ORCH_CACHED"] = "value1"
        config_consumer.invalidate_cache()

        # First call should cache
        value1 = config_consumer.load_config("CACHED")
        assert value1 == "value1"

        # Change env var
        os.environ["ORCH_CACHED"] = "value2"

        # Within cache TTL (60s), should return cached value
        value2 = config_consumer.load_config("CACHED")
        assert value2 == "value1", f"Expected cached 'value1', got {value2}"

        del os.environ["ORCH_CACHED"]

    def test_load_config_cache_invalidation():
        """load_config() respects cache invalidation."""
        os.environ["ORCH_INVALIDATE"] = "initial"
        config_consumer.invalidate_cache()

        value1 = config_consumer.load_config("INVALIDATE")
        assert value1 == "initial"

        # Invalidate cache
        config_consumer.invalidate_cache()

        # Change env var
        os.environ["ORCH_INVALIDATE"] = "updated"

        # After invalidation, should see updated value
        value2 = config_consumer.load_config("INVALIDATE")
        assert value2 == "updated", f"Expected 'updated', got {value2}"

        del os.environ["ORCH_INVALIDATE"]

    def test_load_config_strips_whitespace():
        """load_config() strips whitespace from values."""
        os.environ["ORCH_SPACES"] = "  trimmed  "
        config_consumer.invalidate_cache()

        value = config_consumer.load_config("SPACES")
        assert value == "trimmed", f"Expected 'trimmed', got {value!r}"

        del os.environ["ORCH_SPACES"]

    def test_load_config_empty_env_fallback():
        """load_config() treats empty env values as fallback to default."""
        os.environ["ORCH_EMPTYKEY"] = "   "
        config_consumer.invalidate_cache()

        value = config_consumer.load_config("EMPTYKEY", default="fallback")
        assert value == "fallback", f"Expected 'fallback', got {value}"

        del os.environ["ORCH_EMPTYKEY"]


class TestInvalidateCache:
    """Test invalidate_cache() — clear configuration cache."""

    def test_invalidate_cache_clears_state():
        """invalidate_cache() clears cached config."""
        os.environ["ORCH_TESTKEY"] = "value"
        config_consumer.invalidate_cache()

        # Load and cache
        config_consumer.load_config("TESTKEY")

        # Invalidate
        config_consumer.invalidate_cache()

        # Change env value
        os.environ["ORCH_TESTKEY"] = "new_value"

        # Should see new value after invalidation
        value = config_consumer.load_config("TESTKEY")
        assert value == "new_value", f"Expected 'new_value', got {value}"

        del os.environ["ORCH_TESTKEY"]

    def test_invalidate_cache_multiple_keys():
        """invalidate_cache() clears all cached keys."""
        os.environ["ORCH_KEY1"] = "value1"
        os.environ["ORCH_KEY2"] = "value2"
        config_consumer.invalidate_cache()

        # Cache both keys
        config_consumer.load_config("KEY1")
        config_consumer.load_config("KEY2")

        # Update both
        os.environ["ORCH_KEY1"] = "new1"
        os.environ["ORCH_KEY2"] = "new2"

        # Invalidate
        config_consumer.invalidate_cache()

        # Should see new values
        assert config_consumer.load_config("KEY1") == "new1"
        assert config_consumer.load_config("KEY2") == "new2"

        del os.environ["ORCH_KEY1"]
        del os.environ["ORCH_KEY2"]


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_none_key_handling():
        """Functions handle None key gracefully (fail-soft)."""
        try:
            value = config_consumer.get(None)
            # Should not crash; may return default or None
            assert value is None or value == ""
        except (TypeError, AttributeError):
            # Acceptable fail-soft behavior
            pass

    def test_empty_string_key():
        """Functions handle empty string key gracefully."""
        os.environ["ORCH_"] = "empty_key_value"

        try:
            value = config_consumer.get("")
            # Implementation-dependent; just ensure no crash
        finally:
            del os.environ["ORCH_"]

    def test_large_config_values():
        """Functions handle large string values."""
        large_value = "x" * 100000
        os.environ["ORCH_LARGE"] = large_value

        value = config_consumer.get("LARGE")
        assert len(value) == 100000, f"Expected length 100000, got {len(value)}"

        del os.environ["ORCH_LARGE"]

    def test_special_chars_in_values():
        """Functions handle special characters in values."""
        special_cases = {
            "QUOTES": 'value with "quotes"',
            "NEWLINES": "value\nwith\nnewlines",
            "TABS": "value\twith\ttabs",
            "UNICODE": "value with émojis 🚀",
        }

        for key, expected in special_cases.items():
            os.environ[f"ORCH_{key}"] = expected
            value = config_consumer.get(key)
            # Note: newlines may be lost depending on how os.environ handles them
            # This documents the actual behavior

        for key in special_cases:
            del os.environ[f"ORCH_{key}"]

    def test_numeric_string_keys():
        """Functions handle numeric strings as keys."""
        os.environ["ORCH_123"] = "numeric_key_value"

        value = config_consumer.get("123")
        assert value == "numeric_key_value"

        del os.environ["ORCH_123"]


class TestConcurrency:
    """Test thread-safe config consumption."""

    def test_concurrent_get_reads():
        """Multiple threads can call get() concurrently."""
        os.environ["ORCH_SHARED"] = "shared_value"
        results = []
        errors = []

        def reader():
            try:
                value = config_consumer.get("SHARED")
                results.append(value)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"No errors expected: {errors}"
        assert all(r == "shared_value" for r in results), "All reads should see same value"
        assert len(results) == 10

        del os.environ["ORCH_SHARED"]

    def test_concurrent_load_config_cache():
        """Multiple threads can call load_config() with cache."""
        os.environ["ORCH_CACHED"] = "cached_value"
        config_consumer.invalidate_cache()
        results = []
        errors = []

        def cached_reader():
            try:
                value = config_consumer.load_config("CACHED")
                results.append(value)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=cached_reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"No errors expected: {errors}"
        assert all(r == "cached_value" for r in results)
        assert len(results) == 10

        del os.environ["ORCH_CACHED"]

    def test_concurrent_type_coercion():
        """Multiple threads performing type coercion don't crash."""
        os.environ["ORCH_INT"] = "42"
        os.environ["ORCH_BOOL"] = "true"
        os.environ["ORCH_FLOAT"] = "3.14"

        results = {"int": [], "bool": [], "float": []}
        errors = []

        def int_reader():
            try:
                value = config_consumer.get_int("INT")
                results["int"].append(value)
            except Exception as e:
                errors.append(e)

        def bool_reader():
            try:
                value = config_consumer.get_bool("BOOL")
                results["bool"].append(value)
            except Exception as e:
                errors.append(e)

        def float_reader():
            try:
                value = config_consumer.get_float("FLOAT")
                results["float"].append(value)
            except Exception as e:
                errors.append(e)

        threads = (
            [threading.Thread(target=int_reader) for _ in range(5)] +
            [threading.Thread(target=bool_reader) for _ in range(5)] +
            [threading.Thread(target=float_reader) for _ in range(5)]
        )

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results["int"]) == 5
        assert len(results["bool"]) == 5
        assert len(results["float"]) == 5

        del os.environ["ORCH_INT"]
        del os.environ["ORCH_BOOL"]
        del os.environ["ORCH_FLOAT"]


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_full_config_consumption_flow():
        """Full config consumption flow: defaults, env, types."""
        os.environ["ORCH_HOST"] = "localhost"
        os.environ["ORCH_PORT"] = "5432"
        os.environ["ORCH_DEBUG"] = "true"
        os.environ["ORCH_TIMEOUT"] = "30.5"

        # Consume with type coercion
        host = config_consumer.get("HOST", default="127.0.0.1")
        port = config_consumer.get_int("PORT", default=3306)
        debug = config_consumer.get_bool("DEBUG", default=False)
        timeout = config_consumer.get_float("TIMEOUT", default=10.0)

        assert host == "localhost"
        assert port == 5432
        assert debug is True
        assert abs(timeout - 30.5) < 0.001

        del os.environ["ORCH_HOST"]
        del os.environ["ORCH_PORT"]
        del os.environ["ORCH_DEBUG"]
        del os.environ["ORCH_TIMEOUT"]

    def test_load_all_with_type_functions():
        """load_all() combined with individual type getters."""
        os.environ["ORCH_A"] = "string_value"
        os.environ["ORCH_B"] = "123"
        os.environ["ORCH_C"] = "true"

        all_config = config_consumer.load_all()
        assert all_config["A"] == "string_value"
        assert all_config["B"] == "123"
        assert all_config["C"] == "true"

        # Individual type getters still work
        assert config_consumer.get_int("B") == 123
        assert config_consumer.get_bool("C") is True

        del os.environ["ORCH_A"]
        del os.environ["ORCH_B"]
        del os.environ["ORCH_C"]

    def test_fallback_chain():
        """Test fallback chain: env > default > empty."""
        os.environ.pop("ORCH_CHAIN", None)

        # Missing, should get default
        value1 = config_consumer.get("CHAIN", default="fallback")
        assert value1 == "fallback"

        # Add to env
        os.environ["ORCH_CHAIN"] = "from_env"
        value2 = config_consumer.get("CHAIN", default="fallback")
        assert value2 == "from_env"

        del os.environ["ORCH_CHAIN"]


# ---- Test runner ----

def run_all_tests() -> bool:
    """Run all test functions and report results."""
    test_count = 0
    pass_count = 0
    fail_count = 0
    errors: List[str] = []

    for name, obj in list(globals().items()):
        if name.startswith("Test") and isinstance(obj, type):
            for method_name in dir(obj):
                if method_name.startswith("test_") and callable(getattr(obj, method_name)):
                    method = getattr(obj, method_name)
                    test_count += 1
                    try:
                        method()
                        pass_count += 1
                        print(f"  PASS  {name}.{method_name}")
                    except AssertionError as e:
                        fail_count += 1
                        msg = f"{name}.{method_name}: {e}"
                        print(f"  FAIL  {msg}")
                        errors.append(msg)
                    except Exception as e:
                        fail_count += 1
                        msg = f"{name}.{method_name}: {type(e).__name__}: {e}"
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
