#!/usr/bin/env python3
"""
Comprehensive tests for env_parsing.py fail-soft environment variable parsing.

Tests all code paths including:
- Missing environment variables
- Malformed values
- Bounds checking
- Type coercion
- Edge cases
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env_parsing


class TestParseInt(unittest.TestCase):
    """Tests for parse_int()."""

    def test_valid_int_string(self):
        """Valid integer strings parse correctly."""
        with patch.dict(os.environ, {"TEST_INT": "42"}):
            self.assertEqual(env_parsing.parse_int("TEST_INT", 0), 42)

    def test_negative_int(self):
        """Negative integers parse correctly."""
        with patch.dict(os.environ, {"TEST_INT": "-10"}):
            self.assertEqual(env_parsing.parse_int("TEST_INT", 0), -10)

    def test_missing_env_var(self):
        """Missing env var returns default."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(env_parsing.parse_int("NONEXISTENT", 99), 99)

    def test_empty_string(self):
        """Empty string returns default."""
        with patch.dict(os.environ, {"TEST_INT": ""}):
            self.assertEqual(env_parsing.parse_int("TEST_INT", 77), 77)

    def test_whitespace_only(self):
        """Whitespace-only string returns default."""
        with patch.dict(os.environ, {"TEST_INT": "   "}):
            self.assertEqual(env_parsing.parse_int("TEST_INT", 88), 88)

    def test_non_numeric_string(self):
        """Non-numeric string returns default."""
        with patch.dict(os.environ, {"TEST_INT": "not_a_number"}):
            self.assertEqual(env_parsing.parse_int("TEST_INT", 50), 50)

    def test_float_string(self):
        """Float string returns default (int parsing fails)."""
        with patch.dict(os.environ, {"TEST_INT": "3.14"}):
            self.assertEqual(env_parsing.parse_int("TEST_INT", 0), 0)

    def test_minimum_bound_respected(self):
        """Values below minimum are clamped to minimum."""
        with patch.dict(os.environ, {"TEST_INT": "5"}):
            self.assertEqual(env_parsing.parse_int("TEST_INT", 0, minimum=10), 10)

    def test_maximum_bound_respected(self):
        """Values above maximum are clamped to maximum."""
        with patch.dict(os.environ, {"TEST_INT": "100"}):
            self.assertEqual(env_parsing.parse_int("TEST_INT", 0, maximum=50), 50)

    def test_within_bounds(self):
        """Values within bounds pass through unchanged."""
        with patch.dict(os.environ, {"TEST_INT": "25"}):
            self.assertEqual(env_parsing.parse_int("TEST_INT", 0, minimum=10, maximum=50), 25)

    def test_zero_is_valid(self):
        """Zero is a valid integer."""
        with patch.dict(os.environ, {"TEST_INT": "0"}):
            self.assertEqual(env_parsing.parse_int("TEST_INT", -1), 0)

    def test_leading_trailing_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped before parsing."""
        with patch.dict(os.environ, {"TEST_INT": "  42  "}):
            self.assertEqual(env_parsing.parse_int("TEST_INT", 0), 42)


class TestParseFloat(unittest.TestCase):
    """Tests for parse_float()."""

    def test_valid_float_string(self):
        """Valid float strings parse correctly."""
        with patch.dict(os.environ, {"TEST_FLOAT": "3.14"}):
            self.assertAlmostEqual(env_parsing.parse_float("TEST_FLOAT", 0.0), 3.14, places=5)

    def test_integer_as_float(self):
        """Integer strings parse as float."""
        with patch.dict(os.environ, {"TEST_FLOAT": "42"}):
            self.assertEqual(env_parsing.parse_float("TEST_FLOAT", 0.0), 42.0)

    def test_negative_float(self):
        """Negative floats parse correctly."""
        with patch.dict(os.environ, {"TEST_FLOAT": "-2.5"}):
            self.assertAlmostEqual(env_parsing.parse_float("TEST_FLOAT", 0.0), -2.5, places=5)

    def test_scientific_notation(self):
        """Scientific notation parses correctly."""
        with patch.dict(os.environ, {"TEST_FLOAT": "1.5e-2"}):
            self.assertAlmostEqual(env_parsing.parse_float("TEST_FLOAT", 0.0), 0.015, places=5)

    def test_missing_env_var(self):
        """Missing env var returns default."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(env_parsing.parse_float("NONEXISTENT", 99.9), 99.9)

    def test_empty_string(self):
        """Empty string returns default."""
        with patch.dict(os.environ, {"TEST_FLOAT": ""}):
            self.assertEqual(env_parsing.parse_float("TEST_FLOAT", 77.7), 77.7)

    def test_non_numeric_string(self):
        """Non-numeric string returns default."""
        with patch.dict(os.environ, {"TEST_FLOAT": "not_a_float"}):
            self.assertEqual(env_parsing.parse_float("TEST_FLOAT", 50.0), 50.0)

    def test_minimum_bound_respected(self):
        """Values below minimum are clamped to minimum."""
        with patch.dict(os.environ, {"TEST_FLOAT": "2.5"}):
            self.assertEqual(env_parsing.parse_float("TEST_FLOAT", 0.0, minimum=5.0), 5.0)

    def test_maximum_bound_respected(self):
        """Values above maximum are clamped to maximum."""
        with patch.dict(os.environ, {"TEST_FLOAT": "100.0"}):
            self.assertEqual(env_parsing.parse_float("TEST_FLOAT", 0.0, maximum=50.0), 50.0)

    def test_within_bounds(self):
        """Values within bounds pass through unchanged."""
        with patch.dict(os.environ, {"TEST_FLOAT": "25.5"}):
            result = env_parsing.parse_float("TEST_FLOAT", 0.0, minimum=10.0, maximum=50.0)
            self.assertAlmostEqual(result, 25.5, places=5)

    def test_zero_is_valid(self):
        """Zero is a valid float."""
        with patch.dict(os.environ, {"TEST_FLOAT": "0.0"}):
            self.assertEqual(env_parsing.parse_float("TEST_FLOAT", -1.0), 0.0)

    def test_leading_trailing_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped before parsing."""
        with patch.dict(os.environ, {"TEST_FLOAT": "  3.14  "}):
            self.assertAlmostEqual(env_parsing.parse_float("TEST_FLOAT", 0.0), 3.14, places=5)


class TestParseBool(unittest.TestCase):
    """Tests for parse_bool()."""

    def test_true_values(self):
        """Recognized true values."""
        for val in ["1", "true", "yes", "on", "TRUE", "True", "YES", "ON"]:
            with patch.dict(os.environ, {"TEST_BOOL": val}):
                self.assertTrue(env_parsing.parse_bool("TEST_BOOL"))

    def test_false_values(self):
        """Recognized false values."""
        for val in ["0", "false", "no", "off", "FALSE", "False", "NO", "OFF"]:
            with patch.dict(os.environ, {"TEST_BOOL": val}):
                self.assertFalse(env_parsing.parse_bool("TEST_BOOL"))

    def test_missing_env_var_default_false(self):
        """Missing env var returns False by default."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(env_parsing.parse_bool("NONEXISTENT"))

    def test_missing_env_var_custom_default(self):
        """Missing env var returns custom default."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(env_parsing.parse_bool("NONEXISTENT", default=True))

    def test_empty_string(self):
        """Empty string returns default."""
        with patch.dict(os.environ, {"TEST_BOOL": ""}):
            self.assertFalse(env_parsing.parse_bool("TEST_BOOL", default=False))

    def test_unrecognized_value(self):
        """Unrecognized values return default."""
        with patch.dict(os.environ, {"TEST_BOOL": "maybe"}):
            self.assertTrue(env_parsing.parse_bool("TEST_BOOL", default=True))
            self.assertFalse(env_parsing.parse_bool("TEST_BOOL", default=False))

    def test_whitespace_only(self):
        """Whitespace-only returns default."""
        with patch.dict(os.environ, {"TEST_BOOL": "   "}):
            self.assertTrue(env_parsing.parse_bool("TEST_BOOL", default=True))

    def test_case_insensitive(self):
        """Case doesn't matter."""
        test_cases = [
            ("TrUe", True),
            ("yEs", True),
            ("On", True),
            ("FaLsE", False),
            ("nO", False),
        ]
        for val, expected in test_cases:
            with patch.dict(os.environ, {"TEST_BOOL": val}):
                self.assertEqual(env_parsing.parse_bool("TEST_BOOL"), expected)


class TestParseStr(unittest.TestCase):
    """Tests for parse_str()."""

    def test_normal_string(self):
        """Normal strings pass through."""
        with patch.dict(os.environ, {"TEST_STR": "hello"}):
            self.assertEqual(env_parsing.parse_str("TEST_STR"), "hello")

    def test_empty_string_returns_default(self):
        """Empty string returns default."""
        with patch.dict(os.environ, {"TEST_STR": ""}):
            self.assertEqual(env_parsing.parse_str("TEST_STR", "default"), "default")

    def test_missing_env_var(self):
        """Missing env var returns default."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(env_parsing.parse_str("NONEXISTENT", "fallback"), "fallback")

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped."""
        with patch.dict(os.environ, {"TEST_STR": "  hello  "}):
            self.assertEqual(env_parsing.parse_str("TEST_STR"), "hello")

    def test_whitespace_only_returns_default(self):
        """Whitespace-only string returns default."""
        with patch.dict(os.environ, {"TEST_STR": "   "}):
            self.assertEqual(env_parsing.parse_str("TEST_STR", "default"), "default")

    def test_numeric_string(self):
        """Numeric strings are returned as strings."""
        with patch.dict(os.environ, {"TEST_STR": "12345"}):
            self.assertEqual(env_parsing.parse_str("TEST_STR"), "12345")

    def test_special_characters(self):
        """Special characters are preserved."""
        with patch.dict(os.environ, {"TEST_STR": "hello@world.com!"}):
            self.assertEqual(env_parsing.parse_str("TEST_STR"), "hello@world.com!")

    def test_empty_default(self):
        """Empty default is used for missing/empty vars."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(env_parsing.parse_str("NONEXISTENT"), "")


class TestIntegrationWithRealEnv(unittest.TestCase):
    """Integration tests with actual environment modifications."""

    def setUp(self):
        self.original_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_parse_int_with_actual_env(self):
        """parse_int works with actual environment."""
        os.environ["TEST_PARSE_INT"] = "123"
        self.assertEqual(env_parsing.parse_int("TEST_PARSE_INT", 0), 123)
        del os.environ["TEST_PARSE_INT"]
        self.assertEqual(env_parsing.parse_int("TEST_PARSE_INT", 0), 0)

    def test_parse_float_with_actual_env(self):
        """parse_float works with actual environment."""
        os.environ["TEST_PARSE_FLOAT"] = "2.71"
        self.assertAlmostEqual(env_parsing.parse_float("TEST_PARSE_FLOAT", 0.0), 2.71, places=5)
        del os.environ["TEST_PARSE_FLOAT"]
        self.assertEqual(env_parsing.parse_float("TEST_PARSE_FLOAT", 0.0), 0.0)

    def test_concurrent_parses_are_safe(self):
        """Multiple threads parsing env vars don't interfere."""
        import threading
        results = []
        errors = []

        def parse_many():
            try:
                os.environ["THREAD_TEST"] = "42"
                for _ in range(100):
                    val = env_parsing.parse_int("THREAD_TEST", 0)
                    results.append(val)
                del os.environ["THREAD_TEST"]
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=parse_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
        self.assertEqual(len(results), 500)
        self.assertTrue(all(v == 42 for v in results))


if __name__ == "__main__":
    unittest.main()
