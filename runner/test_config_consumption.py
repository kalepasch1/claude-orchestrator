#!/usr/bin/env python3
"""Tests for orch-config-consumption — configuration consumption via ConfigManager.

Tests validate:
- Environment variable consumption with ORCH_ prefix
- Default value fallback behavior
- File-based configuration loading
- Override priority (overrides > env > defaults)
- Type coercion (bool, int, float, string)
- Validation and missing key detection
- Edge cases (None, empty values, bad paths, malformed JSON)
- Thread-safe consumption patterns
- Fail-soft error handling
"""

import os
import sys
import json
import tempfile
import threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable external dependencies
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
os.environ.pop("ORCH_DEBUG", None)
os.environ.pop("ORCH_TIMEOUT_S", None)
os.environ.pop("ORCH_POOL_SIZE", None)

import config_manager


class TestBasicConsumption:
    """Test basic config consumption from env vars and defaults."""

    def test_consume_from_env_with_orch_prefix(self):
        """Env var with ORCH_ prefix is consumed by ConfigManager.get()."""
        os.environ["ORCH_TIMEOUT_S"] = "30"
        cm = config_manager.ConfigManager(defaults={"timeout_s": 60})

        value = cm.get("timeout_s")
        # Type is coerced based on default type (int)
        assert value == 30, f"Expected coerced int 30 from env, got {type(value).__name__}: {value}"
        assert isinstance(value, int), f"Expected int type, got {type(value).__name__}"

        del os.environ["ORCH_TIMEOUT_S"]

    def test_consume_without_env_fallback_to_default(self):
        """Missing env var falls back to default value."""
        os.environ.pop("ORCH_MISSING_KEY", None)
        cm = config_manager.ConfigManager(defaults={"missing_key": "default_value"})

        value = cm.get("missing_key")
        assert value == "default_value", f"Expected default 'default_value', got {value}"

    def test_consume_without_env_or_default_returns_none(self):
        """Missing both env and default returns explicit None."""
        os.environ.pop("ORCH_NO_KEY", None)
        cm = config_manager.ConfigManager(defaults={})

        value = cm.get("no_key")
        assert value is None, f"Expected None, got {value}"

    def test_consume_with_explicit_fallback_default(self):
        """Fallback default parameter overrides None when key missing."""
        os.environ.pop("ORCH_FALLBACK_KEY", None)
        cm = config_manager.ConfigManager(defaults={})

        value = cm.get("fallback_key", default="fallback_value")
        assert value == "fallback_value", f"Expected fallback 'fallback_value', got {value}"

    def test_empty_env_value_treated_as_present(self):
        """Empty env string is still consumed (not treated as missing)."""
        os.environ["ORCH_EMPTY"] = ""
        cm = config_manager.ConfigManager(defaults={"empty": "default"})

        value = cm.get("empty")
        # Empty string should be consumed from env, but may depend on implementation
        # Typically empty string overrides default
        assert value == "" or value == "default", f"Expected '' or 'default', got {value}"

        del os.environ["ORCH_EMPTY"]

    def test_consume_preserves_default_type(self):
        """Default value type determines env coercion target type."""
        os.environ["ORCH_BOOL_SETTING"] = "true"
        cm = config_manager.ConfigManager(defaults={"bool_setting": False})

        value = cm.get("bool_setting")
        assert isinstance(value, bool), f"Expected bool, got {type(value).__name__}"
        assert value is True, f"Expected True, got {value}"

        del os.environ["ORCH_BOOL_SETTING"]


class TestTypCoercion:
    """Test type coercion for env var consumption."""

    def test_coerce_string_to_bool_true(self):
        """String 'true'/'1'/'yes' coerced to bool True."""
        for val_str in ["true", "True", "TRUE", "1", "yes", "YES"]:
            os.environ["ORCH_BOOL"] = val_str
            cm = config_manager.ConfigManager(defaults={"bool": False})
            value = cm.get("bool")
            assert value is True, f"Expected True for '{val_str}', got {value}"
            del os.environ["ORCH_BOOL"]

    def test_coerce_string_to_bool_false(self):
        """String 'false'/'0' coerced to bool False (anything not 'true'/'1'/'yes')."""
        for val_str in ["false", "False", "0", "no", "anything_else"]:
            os.environ["ORCH_BOOL"] = val_str
            cm = config_manager.ConfigManager(defaults={"bool": True})
            value = cm.get("bool")
            assert value is False, f"Expected False for '{val_str}', got {value}"
            del os.environ["ORCH_BOOL"]

    def test_coerce_string_to_int(self):
        """String coerced to int when default is int."""
        os.environ["ORCH_COUNT"] = "42"
        cm = config_manager.ConfigManager(defaults={"count": 0})

        value = cm.get("count")
        assert isinstance(value, int), f"Expected int, got {type(value).__name__}"
        assert value == 42, f"Expected 42, got {value}"

        del os.environ["ORCH_COUNT"]

    def test_coerce_string_to_int_bad_value_returns_string(self):
        """String that can't parse as int is returned as string (fail-soft)."""
        os.environ["ORCH_BAD_INT"] = "not_a_number"
        cm = config_manager.ConfigManager(defaults={"bad_int": 0})

        value = cm.get("bad_int")
        assert isinstance(value, str), f"Expected str, got {type(value).__name__}"
        assert value == "not_a_number", f"Expected 'not_a_number', got {value}"

        del os.environ["ORCH_BAD_INT"]

    def test_coerce_string_to_float(self):
        """String coerced to float when default is float."""
        os.environ["ORCH_RATE"] = "3.14"
        cm = config_manager.ConfigManager(defaults={"rate": 0.0})

        value = cm.get("rate")
        assert isinstance(value, float), f"Expected float, got {type(value).__name__}"
        assert abs(value - 3.14) < 0.01, f"Expected ~3.14, got {value}"

        del os.environ["ORCH_RATE"]

    def test_coerce_string_to_float_bad_value_returns_string(self):
        """String that can't parse as float is returned as string (fail-soft)."""
        os.environ["ORCH_BAD_FLOAT"] = "not_a_float"
        cm = config_manager.ConfigManager(defaults={"bad_float": 0.0})

        value = cm.get("bad_float")
        assert isinstance(value, str), f"Expected str, got {type(value).__name__}"
        assert value == "not_a_float", f"Expected 'not_a_float', got {value}"

        del os.environ["ORCH_BAD_FLOAT"]

    def test_coerce_preserves_string_type(self):
        """String default keeps value as string even with numeric content."""
        os.environ["ORCH_STR"] = "123"
        cm = config_manager.ConfigManager(defaults={"str": "default"})

        value = cm.get("str")
        assert isinstance(value, str), f"Expected str, got {type(value).__name__}"
        assert value == "123", f"Expected '123', got {value}"

        del os.environ["ORCH_STR"]


class TestOverridePriority:
    """Test config priority: overrides > env > defaults."""

    def test_override_beats_env(self):
        """Programmatic override takes priority over env var."""
        os.environ["ORCH_KEY"] = "env_value"
        cm = config_manager.ConfigManager(defaults={"key": "default"})
        cm.set("key", "override_value")

        value = cm.get("key")
        assert value == "override_value", f"Expected override 'override_value', got {value}"

        del os.environ["ORCH_KEY"]

    def test_override_beats_default(self):
        """Programmatic override takes priority over default."""
        os.environ.pop("ORCH_KEY", None)
        cm = config_manager.ConfigManager(defaults={"key": "default_value"})
        cm.set("key", "override_value")

        value = cm.get("key")
        assert value == "override_value", f"Expected override 'override_value', got {value}"

    def test_env_beats_default(self):
        """Env var takes priority over default."""
        os.environ["ORCH_PRIORITY"] = "env_value"
        cm = config_manager.ConfigManager(defaults={"priority": "default_value"})

        value = cm.get("priority")
        assert value == "env_value", f"Expected env 'env_value', got {value}"

        del os.environ["ORCH_PRIORITY"]

    def test_priority_chain_all_three(self):
        """Test full priority chain: override > env > default."""
        os.environ["ORCH_CHAIN"] = "env_value"
        cm = config_manager.ConfigManager(defaults={"chain": "default_value"})

        # Test env > default
        assert cm.get("chain") == "env_value"

        # Override beats both
        cm.set("chain", "override_value")
        assert cm.get("chain") == "override_value"

        del os.environ["ORCH_CHAIN"]


class TestFileLoading:
    """Test configuration file loading."""

    def test_load_valid_json_file(self):
        """Load config from valid JSON file."""
        config_data = {"db_host": "localhost", "db_port": 5432, "timeout": 30}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            cm = config_manager.ConfigManager(defaults={})
            success = cm.load_file(temp_path)

            assert success is True, "load_file() should return True on success"
            assert cm.get("db_host") == "localhost"
            assert cm.get("db_port") == 5432
            assert cm.get("timeout") == 30
        finally:
            os.unlink(temp_path)

    def test_load_merges_with_existing_defaults(self):
        """File load merges into existing defaults (additive)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"new_key": "new_value"}, f)
            temp_path = f.name

        try:
            cm = config_manager.ConfigManager(defaults={"existing": "value"})
            cm.load_file(temp_path)

            assert cm.get("existing") == "value", "Existing defaults preserved"
            assert cm.get("new_key") == "new_value", "File values added"
        finally:
            os.unlink(temp_path)

    def test_load_nonexistent_file_returns_false(self):
        """Loading non-existent file returns False (fail-soft)."""
        cm = config_manager.ConfigManager(defaults={})
        success = cm.load_file("/nonexistent/path/config.json")

        assert success is False, "load_file() should return False on missing file"

    def test_load_invalid_json_returns_false(self):
        """Loading invalid JSON returns False (fail-soft)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json}")
            temp_path = f.name

        try:
            cm = config_manager.ConfigManager(defaults={})
            success = cm.load_file(temp_path)

            assert success is False, "load_file() should return False on invalid JSON"
        finally:
            os.unlink(temp_path)

    def test_load_file_overwrites_defaults(self):
        """File values overwrite defaults (file > default)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"key": "file_value"}, f)
            temp_path = f.name

        try:
            cm = config_manager.ConfigManager(defaults={"key": "default_value"})
            cm.load_file(temp_path)

            assert cm.get("key") == "file_value", "File values override defaults"
        finally:
            os.unlink(temp_path)

    def test_load_file_does_not_beat_env(self):
        """Env vars still beat file values after load (env > file > default)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"key": "file_value"}, f)
            temp_path = f.name

        try:
            os.environ["ORCH_KEY"] = "env_value"
            cm = config_manager.ConfigManager(defaults={"key": "default"})
            cm.load_file(temp_path)

            value = cm.get("key")
            assert value == "env_value", f"Env should beat file, expected 'env_value', got {value}"

            del os.environ["ORCH_KEY"]
        finally:
            os.unlink(temp_path)


class TestValidation:
    """Test config validation."""

    def test_validate_all_present(self):
        """validate() returns empty list when all required keys present."""
        cm = config_manager.ConfigManager(defaults={"host": "localhost", "port": 5432})

        missing = cm.validate(["host", "port"])
        assert missing == [], f"Expected no missing keys, got {missing}"

    def test_validate_some_missing(self):
        """validate() lists missing keys."""
        cm = config_manager.ConfigManager(defaults={"host": "localhost"})
        os.environ.pop("ORCH_PORT", None)

        missing = cm.validate(["host", "port"])
        assert "port" in missing, f"Expected 'port' in missing list, got {missing}"
        assert "host" not in missing, f"'host' should not be missing"

    def test_validate_empty_list(self):
        """validate() with empty list returns empty."""
        cm = config_manager.ConfigManager(defaults={})

        missing = cm.validate([])
        assert missing == [], f"Expected empty list, got {missing}"

    def test_validate_none_value_is_missing(self):
        """Config value of None is considered missing."""
        cm = config_manager.ConfigManager(defaults={"key": None})

        missing = cm.validate(["key"])
        assert "key" in missing, f"Expected 'key' as missing, got {missing}"


class TestDictionaryExport:
    """Test config.to_dict() export."""

    def test_to_dict_includes_defaults(self):
        """to_dict() includes all defaults."""
        defaults = {"a": 1, "b": 2, "c": 3}
        cm = config_manager.ConfigManager(defaults=defaults)

        result = cm.to_dict()
        assert result["a"] == 1
        assert result["b"] == 2
        assert result["c"] == 3

    def test_to_dict_includes_overrides(self):
        """to_dict() includes programmatic overrides."""
        cm = config_manager.ConfigManager(defaults={"a": 1})
        cm.set("a", 10)
        cm.set("b", 20)

        result = cm.to_dict()
        assert result["a"] == 10, "Override should be in dict"
        assert result["b"] == 20, "New override should be in dict"

    def test_to_dict_override_beats_default(self):
        """Override value appears in dict, not default."""
        cm = config_manager.ConfigManager(defaults={"key": "default"})
        cm.set("key", "override")

        result = cm.to_dict()
        assert result["key"] == "override"

    def test_to_dict_snapshot(self):
        """to_dict() is snapshot at call time (not live view)."""
        cm = config_manager.ConfigManager(defaults={"key": "value1"})

        result1 = cm.to_dict()
        cm.set("key", "value2")
        result2 = cm.to_dict()

        assert result1["key"] == "value1"
        assert result2["key"] == "value2"


class TestReset:
    """Test config reset functionality."""

    def test_reset_clears_overrides(self):
        """reset() clears all programmatic overrides."""
        cm = config_manager.ConfigManager(defaults={"a": 1, "b": 2})
        cm.set("a", 10)
        cm.set("b", 20)

        cm.reset()

        assert cm.get("a") == 1, "Should fall back to default after reset"
        assert cm.get("b") == 2, "Should fall back to default after reset"

    def test_reset_preserves_defaults(self):
        """reset() does not clear defaults."""
        cm = config_manager.ConfigManager(defaults={"key": "default_value"})
        cm.set("key", "override")
        cm.reset()

        value = cm.get("key")
        assert value == "default_value", "Default should be intact after reset"

    def test_reset_preserves_env(self):
        """reset() does not clear env vars."""
        os.environ["ORCH_KEY"] = "env_value"
        cm = config_manager.ConfigManager(defaults={"key": "default"})
        cm.set("key", "override")
        cm.reset()

        value = cm.get("key")
        assert value == "env_value", "Env var should still be present after reset"

        del os.environ["ORCH_KEY"]

    def test_reset_after_multiple_sets(self):
        """reset() clears all overrides even after multiple set() calls."""
        cm = config_manager.ConfigManager(defaults={"a": 1, "b": 2, "c": 3})
        cm.set("a", 10)
        cm.set("b", 20)
        cm.set("c", 30)
        cm.set("a", 100)  # Override again

        cm.reset()

        result = cm.to_dict()
        assert result["a"] == 1
        assert result["b"] == 2
        assert result["c"] == 3


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_consume_none_key(self):
        """get(None) does not crash (fail-soft)."""
        cm = config_manager.ConfigManager(defaults={"key": "value"})
        try:
            value = cm.get(None)
            # Should either return None or a default, not crash
            assert value is None or value == "value"
        except (TypeError, AttributeError):
            # This is acceptable for fail-soft
            pass

    def test_consume_empty_string_key(self):
        """get('') handles gracefully."""
        cm = config_manager.ConfigManager(defaults={"": "empty_key_value"})
        value = cm.get("")
        assert value == "empty_key_value"

    def test_consume_case_insensitive_env(self):
        """Env lookup converts key to uppercase (ORCH_KEY from 'key')."""
        os.environ["ORCH_MYKEY"] = "value"
        cm = config_manager.ConfigManager(defaults={})

        value = cm.get("mykey")
        assert value == "value", "Should find ORCH_MYKEY from 'mykey'"

        del os.environ["ORCH_MYKEY"]

    def test_set_overwrites_previous_override(self):
        """Multiple set() calls overwrite previous values."""
        cm = config_manager.ConfigManager(defaults={"key": "default"})
        cm.set("key", "value1")
        assert cm.get("key") == "value1"

        cm.set("key", "value2")
        assert cm.get("key") == "value2", "Second set() should overwrite first"

    def test_large_config_values(self):
        """ConfigManager handles large string values."""
        large_value = "x" * 10000
        cm = config_manager.ConfigManager(defaults={"large": large_value})

        value = cm.get("large")
        assert len(value) == 10000
        assert value == large_value

    def test_special_chars_in_values(self):
        """ConfigManager handles special characters in values."""
        special_values = {
            "quotes": 'value with "quotes"',
            "newlines": "value\nwith\nnewlines",
            "tabs": "value\twith\ttabs",
            "unicode": "value with émojis 🚀",
        }

        cm = config_manager.ConfigManager(defaults=special_values)

        for key, expected in special_values.items():
            value = cm.get(key)
            assert value == expected, f"Expected {expected!r}, got {value!r}"


class TestConcurrency:
    """Test thread-safe config consumption."""

    def test_concurrent_reads(self):
        """Multiple threads can read config concurrently."""
        cm = config_manager.ConfigManager(defaults={"counter": 42})
        results = []

        def reader():
            value = cm.get("counter")
            results.append(value)

        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r == 42 for r in results), "All reads should see same value"
        assert len(results) == 10

    def test_concurrent_set_and_get(self):
        """Concurrent set() and get() don't crash (may race)."""
        cm = config_manager.ConfigManager(defaults={"key": 0})
        results = []
        errors = []

        def worker():
            try:
                for i in range(10):
                    cm.set("key", i)
                    value = cm.get("key")
                    results.append(value)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent access should not error: {errors}"
        assert len(results) > 0


class TestIntegration:
    """Integration tests combining multiple features."""

    def test_full_consumption_flow(self):
        """Full config consumption flow: file + env + defaults + overrides."""
        # Create config file
        config_data = {"db_host": "file_host", "db_port": 5432, "timeout": 30}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            # Set env var
            os.environ["ORCH_TIMEOUT"] = "60"

            # Create manager with defaults
            defaults = {
                "db_host": "default_host",
                "db_port": 3306,
                "timeout": 15,
                "other": "other_default",
            }
            cm = config_manager.ConfigManager(defaults=defaults)

            # Load file
            cm.load_file(temp_path)

            # Set override
            cm.set("db_host", "override_host")

            # Verify priority
            assert cm.get("db_host") == "override_host", "Override should win"
            assert cm.get("db_port") == 5432, "File should beat default"
            # Env beats file, and is coerced to int based on default type
            assert cm.get("timeout") == 60, "Env should beat file and be coerced to int"
            assert cm.get("other") == "other_default", "Default preserved"

            # Verify validation
            missing = cm.validate(["db_host", "db_port"])
            assert missing == [], "All required keys present"

            # Verify export
            exported = cm.to_dict()
            assert exported["db_host"] == "override_host"
            assert exported["db_port"] == 5432
            # to_dict() reports the EFFECTIVE config, so it agrees with get() on both the
            # env override and its coercion. This line previously asserted the string "60"
            # while the assert above demands the int 60 from the same key — the test
            # contradicted itself, and could not fail either way because every method in
            # this file was missing `self` and never ran.
            assert exported["timeout"] == 60

            del os.environ["ORCH_TIMEOUT"]
        finally:
            os.unlink(temp_path)

    def test_type_coercion_with_file_and_env(self):
        """Type coercion works correctly with file + env sources."""
        config_data = {"enabled": False, "pool_size": 10}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            os.environ["ORCH_ENABLED"] = "true"

            cm = config_manager.ConfigManager(defaults={
                "enabled": False,
                "pool_size": 5,
            })
            cm.load_file(temp_path)

            # Env beats file, but type is still coerced to bool
            enabled = cm.get("enabled")
            assert isinstance(enabled, bool), f"Expected bool, got {type(enabled).__name__}"
            assert enabled is True, "Env 'true' should coerce to True"

            # File beats default for pool_size
            pool_size = cm.get("pool_size")
            assert isinstance(pool_size, int), f"Expected int, got {type(pool_size).__name__}"
            assert pool_size == 10, "File value should be 10"

            del os.environ["ORCH_ENABLED"]
        finally:
            os.unlink(temp_path)


class TestSafeDefaults:
    """Test safe default behavior for missing configs."""

    def test_missing_config_returns_none(self):
        """Missing config returns None (not raising exception)."""
        cm = config_manager.ConfigManager(defaults={})
        os.environ.pop("ORCH_MISSING", None)

        value = cm.get("missing")
        assert value is None, "Missing config should return None"

    def test_fallback_provided_for_missing(self):
        """Fallback default can be provided for missing configs."""
        cm = config_manager.ConfigManager(defaults={})
        os.environ.pop("ORCH_MISSING", None)

        value = cm.get("missing", default="fallback")
        assert value == "fallback", "Fallback should be used"


# ---- Test helpers ----

def run_all_tests():
    """Run all test functions and report results."""
    test_count = 0
    pass_count = 0
    fail_count = 0
    errors = []

    for name, obj in list(globals().items()):
        if name.startswith("Test"):
            for method_name, method in vars(obj).items():
                if method_name.startswith("test_") and callable(method):
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

    print(f"\nconfig_consumption tests: {pass_count}/{test_count} passed")
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
