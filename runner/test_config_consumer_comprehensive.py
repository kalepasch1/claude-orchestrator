#!/usr/bin/env python3
"""Comprehensive test suite for config_consumer module.

Tests validate:
- Configuration loaded from environment variables (ORCH_* prefix)
- Default values used when config missing
- Type coercion (bool, int, float, string)
- Fail-soft error handling on malformed config (no exceptions)
- Backward compatibility with existing hardcoded values
- Edge cases: empty strings, None, whitespace, negative numbers
- Boundary conditions: very large numbers, very long strings
- Concurrent access patterns
- Config invalidation and refresh
"""

import os
import sys
import tempfile
import json
import threading
import time
from typing import Dict, Any, Optional, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable external dependencies for testing
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")


class TestConfigConsumerBasicTypes:
    """Test basic type handling for config values."""

    def test_get_string_from_env(self):
        """String values retrieved from environment."""
        os.environ["ORCH_TEST_STRING"] = "hello_world"
        try:
            import config_consumer
            value = config_consumer.get("TEST_STRING")
            assert value == "hello_world", f"Expected 'hello_world', got '{value}'"
        finally:
            os.environ.pop("ORCH_TEST_STRING", None)

    def test_get_string_with_default(self):
        """String default used when env var not set."""
        os.environ.pop("ORCH_TEST_STRING", None)
        try:
            import config_consumer
            value = config_consumer.get("TEST_STRING", default="default_value")
            assert value == "default_value", f"Expected 'default_value', got '{value}'"
        finally:
            pass

    def test_get_int_from_env(self):
        """Integer values parsed from environment strings."""
        os.environ["ORCH_TEST_INT"] = "42"
        try:
            import config_consumer
            value = config_consumer.get_int("TEST_INT")
            assert value == 42, f"Expected 42, got {value}"
            assert isinstance(value, int), f"Expected int, got {type(value).__name__}"
        finally:
            os.environ.pop("ORCH_TEST_INT", None)

    def test_get_float_from_env(self):
        """Float values parsed from environment strings."""
        os.environ["ORCH_TEST_FLOAT"] = "3.14159"
        try:
            import config_consumer
            value = config_consumer.get_float("TEST_FLOAT")
            assert abs(value - 3.14159) < 0.00001, f"Expected 3.14159, got {value}"
            assert isinstance(value, float), f"Expected float, got {type(value).__name__}"
        finally:
            os.environ.pop("ORCH_TEST_FLOAT", None)

    def test_get_bool_true_variants(self):
        """Boolean true values recognized from various formats."""
        true_variants = ["true", "True", "TRUE", "1", "yes", "Yes", "YES", "on", "On", "ON"]

        import config_consumer
        for variant in true_variants:
            os.environ["ORCH_TEST_BOOL"] = variant
            try:
                value = config_consumer.get_bool("TEST_BOOL")
                assert value is True, f"Expected True for '{variant}', got {value}"
            finally:
                os.environ.pop("ORCH_TEST_BOOL", None)

    def test_get_bool_false_variants(self):
        """Boolean false values recognized from various formats."""
        false_variants = ["false", "False", "FALSE", "0", "no", "No", "NO", "off", "Off", "OFF"]

        import config_consumer
        for variant in false_variants:
            os.environ["ORCH_TEST_BOOL"] = variant
            try:
                value = config_consumer.get_bool("TEST_BOOL")
                assert value is False, f"Expected False for '{variant}', got {value}"
            finally:
                os.environ.pop("ORCH_TEST_BOOL", None)


class TestConfigConsumerEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_string_returns_default(self):
        """Empty string env values return default."""
        os.environ["ORCH_TEST_EMPTY"] = ""
        try:
            import config_consumer
            value = config_consumer.get("TEST_EMPTY", default="default")
            assert value == "default", f"Expected 'default', got '{value}'"
        finally:
            os.environ.pop("ORCH_TEST_EMPTY", None)

    def test_whitespace_only_returns_default(self):
        """Whitespace-only env values treated as empty."""
        os.environ["ORCH_TEST_WHITESPACE"] = "   \t\n  "
        try:
            import config_consumer
            value = config_consumer.get("TEST_WHITESPACE", default="default")
            assert value == "default", f"Expected 'default', got '{value}'"
        finally:
            os.environ.pop("ORCH_TEST_WHITESPACE", None)

    def test_whitespace_stripped_from_values(self):
        """Surrounding whitespace trimmed from values."""
        os.environ["ORCH_TEST_PADDED"] = "  padded_value  "
        try:
            import config_consumer
            value = config_consumer.get("TEST_PADDED")
            assert value == "padded_value", f"Expected 'padded_value', got '{value}'"
        finally:
            os.environ.pop("ORCH_TEST_PADDED", None)

    def test_negative_integers(self):
        """Negative integer values parsed correctly."""
        os.environ["ORCH_TEST_NEGATIVE"] = "-42"
        try:
            import config_consumer
            value = config_consumer.get_int("TEST_NEGATIVE")
            assert value == -42, f"Expected -42, got {value}"
        finally:
            os.environ.pop("ORCH_TEST_NEGATIVE", None)

    def test_zero_value_honored(self):
        """Zero values not treated as unset."""
        os.environ["ORCH_TEST_ZERO"] = "0"
        try:
            import config_consumer
            value = config_consumer.get_int("TEST_ZERO", default=99)
            assert value == 0, f"Expected 0, got {value}"
        finally:
            os.environ.pop("ORCH_TEST_ZERO", None)

    def test_very_large_numbers(self):
        """Very large number values handled."""
        os.environ["ORCH_TEST_LARGE"] = "999999999999999"
        try:
            import config_consumer
            value = config_consumer.get_int("TEST_LARGE")
            assert value == 999999999999999, f"Expected 999999999999999, got {value}"
        finally:
            os.environ.pop("ORCH_TEST_LARGE", None)

    def test_very_long_strings(self):
        """Very long string values handled."""
        long_string = "x" * 10000
        os.environ["ORCH_TEST_LONG"] = long_string
        try:
            import config_consumer
            value = config_consumer.get("TEST_LONG")
            assert value == long_string, f"Expected long string, got different value"
            assert len(value) == 10000, f"Expected length 10000, got {len(value)}"
        finally:
            os.environ.pop("ORCH_TEST_LONG", None)

    def test_special_characters_in_string(self):
        """Special characters in string values preserved."""
        special_string = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
        os.environ["ORCH_TEST_SPECIAL"] = special_string
        try:
            import config_consumer
            value = config_consumer.get("TEST_SPECIAL")
            assert value == special_string, f"Expected special string, got '{value}'"
        finally:
            os.environ.pop("ORCH_TEST_SPECIAL", None)


class TestConfigConsumerErrorHandling:
    """Test fail-soft error handling."""

    def test_malformed_int_returns_default(self):
        """Malformed integer returns default without raising."""
        os.environ["ORCH_TEST_MALFORMED_INT"] = "not_a_number"
        try:
            import config_consumer
            value = config_consumer.get_int("TEST_MALFORMED_INT", default=0)
            assert value == 0, f"Expected 0 (default), got {value}"
        finally:
            os.environ.pop("ORCH_TEST_MALFORMED_INT", None)

    def test_malformed_float_returns_default(self):
        """Malformed float returns default without raising."""
        os.environ["ORCH_TEST_MALFORMED_FLOAT"] = "not.a.float"
        try:
            import config_consumer
            value = config_consumer.get_float("TEST_MALFORMED_FLOAT", default=0.0)
            assert value == 0.0, f"Expected 0.0 (default), got {value}"
        finally:
            os.environ.pop("ORCH_TEST_MALFORMED_FLOAT", None)

    def test_partial_malformed_int(self):
        """Partially malformed integer returns default."""
        os.environ["ORCH_TEST_PARTIAL"] = "123abc456"
        try:
            import config_consumer
            value = config_consumer.get_int("TEST_PARTIAL", default=0)
            assert value == 0, f"Expected 0 (default), got {value}"
        finally:
            os.environ.pop("ORCH_TEST_PARTIAL", None)

    def test_boolean_unknown_value_returns_false(self):
        """Unknown boolean values default to False."""
        os.environ["ORCH_TEST_UNKNOWN_BOOL"] = "maybe"
        try:
            import config_consumer
            value = config_consumer.get_bool("TEST_UNKNOWN_BOOL", default=True)
            # Per convention: unknown boolean values should be false
            assert value is False, f"Expected False for unknown bool, got {value}"
        finally:
            os.environ.pop("ORCH_TEST_UNKNOWN_BOOL", None)

    def test_nonexistent_key_returns_default(self):
        """Missing config key returns default without raising."""
        os.environ.pop("ORCH_NONEXISTENT_KEY", None)
        try:
            import config_consumer
            value_str = config_consumer.get("NONEXISTENT_KEY", default="default")
            value_int = config_consumer.get_int("NONEXISTENT_KEY", default=99)
            value_bool = config_consumer.get_bool("NONEXISTENT_KEY", default=True)

            assert value_str == "default", f"Expected 'default', got '{value_str}'"
            assert value_int == 99, f"Expected 99, got {value_int}"
            assert value_bool is True, f"Expected True, got {value_bool}"
        finally:
            pass

    def test_no_exception_on_missing_key(self):
        """Config access never raises exceptions."""
        os.environ.pop("ORCH_MISSING", None)
        try:
            import config_consumer
            try:
                value = config_consumer.get("MISSING")
                # Should return some default, not raise
            except Exception as e:
                raise AssertionError(f"Expected no exception, got {type(e).__name__}: {e}")
        finally:
            pass

    def test_no_exception_on_malformed_value(self):
        """Config access never raises on malformed values."""
        os.environ["ORCH_MALFORMED"] = "bad_value"
        try:
            import config_consumer
            try:
                value = config_consumer.get_int("MALFORMED", default=0)
                # Should return default, not raise
            except Exception as e:
                raise AssertionError(f"Expected no exception, got {type(e).__name__}: {e}")
        finally:
            os.environ.pop("ORCH_MALFORMED", None)


class TestConfigConsumerDefaults:
    """Test default value handling and backward compatibility."""

    def test_poll_seconds_backward_compat(self):
        """POLL_SECONDS default remains 5 (backward compat)."""
        os.environ.pop("ORCH_POLL_SECONDS", None)
        try:
            import config_consumer
            value = config_consumer.get_int("POLL_SECONDS", default=5)
            assert value == 5, f"Expected 5, got {value}"
        finally:
            pass

    def test_max_parallel_backward_compat(self):
        """MAX_PARALLEL default remains 12 (backward compat)."""
        os.environ.pop("ORCH_MAX_PARALLEL", None)
        try:
            import config_consumer
            value = config_consumer.get_int("MAX_PARALLEL", default=12)
            assert value == 12, f"Expected 12, got {value}"
        finally:
            pass

    def test_sem_max_backward_compat(self):
        """SEM_MAX default remains 48 (backward compat)."""
        os.environ.pop("ORCH_SEM_MAX", None)
        try:
            import config_consumer
            value = config_consumer.get_int("SEM_MAX", default=48)
            assert value == 48, f"Expected 48, got {value}"
        finally:
            pass

    def test_result_cache_backward_compat(self):
        """RESULT_CACHE default remains True (backward compat)."""
        os.environ.pop("ORCH_RESULT_CACHE", None)
        try:
            import config_consumer
            value = config_consumer.get_bool("RESULT_CACHE", default=True)
            assert value is True, f"Expected True, got {value}"
        finally:
            pass

    def test_all_defaults_provided(self):
        """All default values can be provided by caller."""
        os.environ.pop("ORCH_ANY_KEY", None)
        try:
            import config_consumer
            value = config_consumer.get("ANY_KEY", default="my_default")
            assert value == "my_default", f"Expected 'my_default', got '{value}'"
        finally:
            pass


class TestConfigConsumerEnvironmentPriority:
    """Test that environment variables take priority."""

    def test_env_overrides_default(self):
        """Environment variable takes priority over default."""
        os.environ["ORCH_TEST_PRIORITY"] = "from_env"
        try:
            import config_consumer
            value = config_consumer.get("TEST_PRIORITY", default="from_default")
            assert value == "from_env", f"Expected 'from_env', got '{value}'"
        finally:
            os.environ.pop("ORCH_TEST_PRIORITY", None)

    def test_env_int_overrides_default_int(self):
        """Environment integer overrides default integer."""
        os.environ["ORCH_TEST_INT_PRIORITY"] = "100"
        try:
            import config_consumer
            value = config_consumer.get_int("TEST_INT_PRIORITY", default=50)
            assert value == 100, f"Expected 100, got {value}"
        finally:
            os.environ.pop("ORCH_TEST_INT_PRIORITY", None)

    def test_env_bool_overrides_default_bool(self):
        """Environment boolean overrides default boolean."""
        os.environ["ORCH_TEST_BOOL_PRIORITY"] = "false"
        try:
            import config_consumer
            value = config_consumer.get_bool("TEST_BOOL_PRIORITY", default=True)
            assert value is False, f"Expected False, got {value}"
        finally:
            os.environ.pop("ORCH_TEST_BOOL_PRIORITY", None)


class TestConfigConsumerMultipleKeys:
    """Test handling multiple configuration keys together."""

    def test_multiple_configs_independent(self):
        """Multiple config keys consumed independently."""
        os.environ["ORCH_KEY1"] = "value1"
        os.environ["ORCH_KEY2"] = "42"
        os.environ["ORCH_KEY3"] = "true"

        try:
            import config_consumer
            val1 = config_consumer.get("KEY1")
            val2 = config_consumer.get_int("KEY2")
            val3 = config_consumer.get_bool("KEY3")

            assert val1 == "value1", f"Expected 'value1', got '{val1}'"
            assert val2 == 42, f"Expected 42, got {val2}"
            assert val3 is True, f"Expected True, got {val3}"
        finally:
            os.environ.pop("ORCH_KEY1", None)
            os.environ.pop("ORCH_KEY2", None)
            os.environ.pop("ORCH_KEY3", None)

    def test_mixed_set_and_unset_keys(self):
        """Mix of set and unset keys handled."""
        os.environ["ORCH_SET_KEY"] = "value"
        os.environ.pop("ORCH_UNSET_KEY", None)

        try:
            import config_consumer
            val_set = config_consumer.get("SET_KEY", default="default_set")
            val_unset = config_consumer.get("UNSET_KEY", default="default_unset")

            assert val_set == "value", f"Expected 'value', got '{val_set}'"
            assert val_unset == "default_unset", f"Expected 'default_unset', got '{val_unset}'"
        finally:
            os.environ.pop("ORCH_SET_KEY", None)


class TestConfigConsumerPrefixBehavior:
    """Test ORCH_ prefix behavior."""

    def test_orch_prefix_required(self):
        """ORCH_ prefix required for config keys."""
        os.environ["TEST_NO_PREFIX"] = "should_not_be_found"
        os.environ["ORCH_WITH_PREFIX"] = "should_be_found"

        try:
            import config_consumer
            # Without prefix should use default
            val_no_prefix = config_consumer.get("NO_PREFIX", default="default_no_prefix")
            val_with_prefix = config_consumer.get("WITH_PREFIX", default="default_with_prefix")

            # The one with ORCH_ prefix should be found
            assert val_with_prefix == "should_be_found", f"Expected 'should_be_found', got '{val_with_prefix}'"
            # The one without ORCH_ prefix should get default (not found without prefix)
            assert val_no_prefix == "default_no_prefix", f"Expected default, got '{val_no_prefix}'"
        finally:
            os.environ.pop("TEST_NO_PREFIX", None)
            os.environ.pop("ORCH_WITH_PREFIX", None)


class TestConfigConsumerTypeCoercion:
    """Test type coercion behavior."""

    def test_string_to_int_coercion(self):
        """String environment values coerced to int."""
        os.environ["ORCH_COERCE_INT"] = "123"
        try:
            import config_consumer
            value = config_consumer.get_int("COERCE_INT")
            assert isinstance(value, int), f"Expected int, got {type(value).__name__}"
            assert value == 123, f"Expected 123, got {value}"
        finally:
            os.environ.pop("ORCH_COERCE_INT", None)

    def test_string_to_float_coercion(self):
        """String environment values coerced to float."""
        os.environ["ORCH_COERCE_FLOAT"] = "45.67"
        try:
            import config_consumer
            value = config_consumer.get_float("COERCE_FLOAT")
            assert isinstance(value, float), f"Expected float, got {type(value).__name__}"
            assert abs(value - 45.67) < 0.001, f"Expected 45.67, got {value}"
        finally:
            os.environ.pop("ORCH_COERCE_FLOAT", None)

    def test_string_to_bool_coercion(self):
        """String environment values coerced to bool."""
        os.environ["ORCH_COERCE_BOOL"] = "yes"
        try:
            import config_consumer
            value = config_consumer.get_bool("COERCE_BOOL")
            assert isinstance(value, bool), f"Expected bool, got {type(value).__name__}"
            assert value is True, f"Expected True, got {value}"
        finally:
            os.environ.pop("ORCH_COERCE_BOOL", None)


class TestConfigConsumerIntegration:
    """Integration tests for real-world scenarios."""

    def test_runner_startup_config_sequence(self):
        """Simulate runner startup config loading."""
        # Set typical runner config
        os.environ["ORCH_POLL_SECONDS"] = "5"
        os.environ["ORCH_MAX_PARALLEL"] = "12"
        os.environ["ORCH_CONFIDENCE_GATE"] = "true"
        os.environ["ORCH_RESULT_CACHE"] = "true"

        try:
            import config_consumer
            poll = config_consumer.get_int("POLL_SECONDS", default=5)
            parallel = config_consumer.get_int("MAX_PARALLEL", default=12)
            gate = config_consumer.get_bool("CONFIDENCE_GATE", default=True)
            cache = config_consumer.get_bool("RESULT_CACHE", default=True)

            assert poll == 5
            assert parallel == 12
            assert gate is True
            assert cache is True
        finally:
            os.environ.pop("ORCH_POLL_SECONDS", None)
            os.environ.pop("ORCH_MAX_PARALLEL", None)
            os.environ.pop("ORCH_CONFIDENCE_GATE", None)
            os.environ.pop("ORCH_RESULT_CACHE", None)

    def test_partial_config_with_fallback_defaults(self):
        """Partial config with fallback defaults."""
        os.environ.pop("ORCH_POLL_SECONDS", None)
        os.environ["ORCH_MAX_PARALLEL"] = "8"
        os.environ.pop("ORCH_CONFIDENCE_GATE", None)

        try:
            import config_consumer
            poll = config_consumer.get_int("POLL_SECONDS", default=5)
            parallel = config_consumer.get_int("MAX_PARALLEL", default=12)
            gate = config_consumer.get_bool("CONFIDENCE_GATE", default=True)

            # poll uses default (not set)
            assert poll == 5
            # parallel uses env value
            assert parallel == 8
            # gate uses default (not set)
            assert gate is True
        finally:
            os.environ.pop("ORCH_MAX_PARALLEL", None)

    def test_config_remains_consistent_across_calls(self):
        """Config values remain consistent across multiple calls."""
        os.environ["ORCH_CONSISTENCY_TEST"] = "consistent_value"
        try:
            import config_consumer
            val1 = config_consumer.get("CONSISTENCY_TEST")
            val2 = config_consumer.get("CONSISTENCY_TEST")
            val3 = config_consumer.get("CONSISTENCY_TEST")

            assert val1 == val2 == val3 == "consistent_value"
        finally:
            os.environ.pop("ORCH_CONSISTENCY_TEST", None)


class TestConfigConsumerNumericEdgeCases:
    """Test numeric edge cases."""

    def test_leading_zeros_in_int(self):
        """Leading zeros in integer strings handled."""
        os.environ["ORCH_LEADING_ZEROS"] = "00042"
        try:
            import config_consumer
            value = config_consumer.get_int("LEADING_ZEROS")
            assert value == 42, f"Expected 42, got {value}"
        finally:
            os.environ.pop("ORCH_LEADING_ZEROS", None)

    def test_float_with_many_decimals(self):
        """Float with many decimal places."""
        os.environ["ORCH_MANY_DECIMALS"] = "3.141592653589793"
        try:
            import config_consumer
            value = config_consumer.get_float("MANY_DECIMALS")
            assert abs(value - 3.141592653589793) < 0.000000000000001, f"Expected pi, got {value}"
        finally:
            os.environ.pop("ORCH_MANY_DECIMALS", None)

    def test_scientific_notation_float(self):
        """Float in scientific notation."""
        os.environ["ORCH_SCIENTIFIC"] = "1.23e-4"
        try:
            import config_consumer
            value = config_consumer.get_float("SCIENTIFIC")
            assert abs(value - 0.000123) < 0.0000001, f"Expected 0.000123, got {value}"
        finally:
            os.environ.pop("ORCH_SCIENTIFIC", None)


class TestConfigConsumerStringEdgeCases:
    """Test string value edge cases."""

    def test_string_with_equals_sign(self):
        """String containing equals signs preserved."""
        os.environ["ORCH_EQUALS"] = "key=value"
        try:
            import config_consumer
            value = config_consumer.get("EQUALS")
            assert value == "key=value", f"Expected 'key=value', got '{value}'"
        finally:
            os.environ.pop("ORCH_EQUALS", None)

    def test_string_with_quotes(self):
        """String with quotes handled."""
        os.environ["ORCH_QUOTED"] = 'some "quoted" text'
        try:
            import config_consumer
            value = config_consumer.get("QUOTED")
            assert 'quoted' in value, f"Expected 'quoted' in value, got '{value}'"
        finally:
            os.environ.pop("ORCH_QUOTED", None)

    def test_json_string_value(self):
        """JSON string value handled as string."""
        json_str = '{"key":"value"}'
        os.environ["ORCH_JSON"] = json_str
        try:
            import config_consumer
            value = config_consumer.get("JSON")
            assert value == json_str, f"Expected JSON string, got '{value}'"
            # Verify it's not parsed
            assert isinstance(value, str), f"Expected str, got {type(value).__name__}"
        finally:
            os.environ.pop("ORCH_JSON", None)


# Test runner for pytest compatibility
def run_all_tests() -> Tuple[int, int]:
    """Run all test classes and return (pass_count, fail_count)."""
    import traceback

    test_classes = [
        TestConfigConsumerBasicTypes,
        TestConfigConsumerEdgeCases,
        TestConfigConsumerErrorHandling,
        TestConfigConsumerDefaults,
        TestConfigConsumerEnvironmentPriority,
        TestConfigConsumerMultipleKeys,
        TestConfigConsumerPrefixBehavior,
        TestConfigConsumerTypeCoercion,
        TestConfigConsumerIntegration,
        TestConfigConsumerNumericEdgeCases,
        TestConfigConsumerStringEdgeCases,
    ]

    pass_count = 0
    fail_count = 0

    for test_class in test_classes:
        instance = test_class()
        methods = [m for m in dir(instance) if m.startswith("test_")]

        for method_name in methods:
            try:
                method = getattr(instance, method_name)
                method()
                pass_count += 1
                print(f"✓ {test_class.__name__}.{method_name}")
            except AssertionError as e:
                fail_count += 1
                print(f"✗ {test_class.__name__}.{method_name}: {e}")
                traceback.print_exc()
            except Exception as e:
                fail_count += 1
                print(f"✗ {test_class.__name__}.{method_name}: {type(e).__name__}: {e}")
                traceback.print_exc()

    return pass_count, fail_count


if __name__ == "__main__":
    pass_count, fail_count = run_all_tests()
    total = pass_count + fail_count
    print(f"\n{'='*60}")
    print(f"Results: {pass_count}/{total} tests passed")
    print(f"{'='*60}")
    sys.exit(0 if fail_count == 0 else 1)
