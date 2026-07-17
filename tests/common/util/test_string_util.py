"""Tests for string_util — including empty/whitespace edge cases."""
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

from common.util.string_util import normalize_whitespace, is_blank


class TestNormalizeWhitespace(unittest.TestCase):
    """Tests for normalize_whitespace."""

    def test_normal_string(self):
        self.assertEqual(normalize_whitespace("hello world"), "hello world")

    def test_empty_string(self):
        """Edge case: empty string input should return empty string."""
        self.assertEqual(normalize_whitespace(""), "")

    def test_whitespace_only(self):
        """Edge case: all-whitespace input should return empty string."""
        self.assertEqual(normalize_whitespace("   "), "")

    def test_none_input(self):
        self.assertEqual(normalize_whitespace(None), "")


class TestIsBlank(unittest.TestCase):
    """Tests for is_blank."""

    def test_empty_string(self):
        """Edge case: empty string is blank."""
        self.assertTrue(is_blank(""))

    def test_whitespace_only(self):
        """Edge case: whitespace-only string is blank."""
        self.assertTrue(is_blank("   "))

    def test_none_is_blank(self):
        self.assertTrue(is_blank(None))

    def test_non_blank(self):
        self.assertFalse(is_blank("hello"))


if __name__ == "__main__":
    unittest.main()
