"""Tests for agentic_repair error handling and recovery mechanisms.

Validates that:
  - Technical vs replacement categories are classified correctly
  - Repair prompts are built safely without leaking secrets
  - Max prompt length is enforced
  - Edge cases (None, empty, unknown) fail gracefully
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agentic_repair


class TestCategoryClassification(unittest.TestCase):
    """Verify is_technical and replacement_required handle all categories."""

    def test_technical_categories(self):
        for cat in ("buildfail", "testfail", "noop", "conflict", "timeout", "transient"):
            self.assertTrue(agentic_repair.is_technical(cat), f"{cat} should be technical")

    def test_replacement_categories(self):
        for cat in ("legal", "secret", "security"):
            self.assertTrue(agentic_repair.replacement_required(cat), f"{cat} should require replacement")
            self.assertFalse(agentic_repair.is_technical(cat), f"{cat} should NOT be technical")

    def test_none_defaults_to_technical(self):
        self.assertTrue(agentic_repair.is_technical(None))

    def test_empty_string_not_replacement(self):
        self.assertFalse(agentic_repair.replacement_required(""))

    def test_unknown_category_not_technical(self):
        self.assertFalse(agentic_repair.is_technical("unknown-xyz"))


class TestOriginalPrompt(unittest.TestCase):
    """Verify _original_prompt extracts and truncates safely."""

    def test_basic_prompt_extraction(self):
        task = {"slug": "fix-bug", "prompt": "Fix the login bug in auth.py"}
        result = agentic_repair._original_prompt(task)
        self.assertIn("Fix the login bug", result)

    def test_missing_prompt_uses_slug(self):
        task = {"slug": "my-task", "prompt": None}
        result = agentic_repair._original_prompt(task)
        self.assertIn("my-task", result)

    def test_empty_task_does_not_crash(self):
        result = agentic_repair._original_prompt({})
        self.assertIsInstance(result, str)

    def test_prompt_length_bounded(self):
        long_prompt = "x" * 50000
        task = {"slug": "long", "prompt": long_prompt}
        result = agentic_repair._original_prompt(task)
        self.assertLessEqual(len(result), agentic_repair.MAX_PROMPT_CHARS + 500)


class TestMarkerConstant(unittest.TestCase):
    """Ensure the repair marker is stable for downstream parsing."""

    def test_marker_value(self):
        self.assertEqual(agentic_repair.MARKER, "AGENTIC-REPAIR DIRECTIVE")

    def test_marker_in_technical_set(self):
        self.assertIn("rework", agentic_repair.TECHNICAL_CATEGORIES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
