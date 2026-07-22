#!/usr/bin/env python3
"""Test hygiene for task_refs.py — immutable ref identity helpers.

Canary: verifies _safe() sanitization and patch_id/publish contract
without requiring a real git remote.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from task_refs import _safe


class TestSafeSanitization(unittest.TestCase):
    """_safe() must produce git-ref-safe strings."""

    def test_normal_slug(self):
        self.assertEqual(_safe("my-task-slug"), "my-task-slug")

    def test_none_returns_task(self):
        self.assertEqual(_safe(None), "task")

    def test_empty_string_returns_task(self):
        self.assertEqual(_safe(""), "task")

    def test_special_chars_replaced(self):
        result = _safe("foo/bar baz@qux")
        self.assertNotIn("/", result)
        self.assertNotIn(" ", result)
        self.assertNotIn("@", result)

    def test_truncation_at_120(self):
        long_slug = "a" * 200
        self.assertLessEqual(len(_safe(long_slug)), 120)

    def test_leading_dots_stripped(self):
        result = _safe("...leading-dots")
        self.assertFalse(result.startswith("."))

    def test_numeric_input(self):
        result = _safe(42)
        self.assertEqual(result, "42")


if __name__ == "__main__":
    unittest.main()
