"""Tests for merge_validator — speculative merge validation."""
import unittest
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestStats(unittest.TestCase):
    def test_returns_dict(self):
        import merge_validator
        s = merge_validator.stats()
        self.assertIsInstance(s, dict)
        self.assertIn("validations_run", s)
        self.assertIn("drafts_passed", s)
        self.assertIn("fast_tracks", s)


class TestConstraintPrompt(unittest.TestCase):
    def test_formats_failures(self):
        import merge_validator
        result = merge_validator.constraint_prompt(["test_auth failed: AssertionError"])
        self.assertIn("Known Test Failures", result)
        self.assertIn("test_auth", result)

    def test_empty_failures(self):
        import merge_validator
        result = merge_validator.constraint_prompt([])
        self.assertEqual(result, "")


class TestFastTrackCheck(unittest.TestCase):
    def test_no_validation_returns_false(self):
        import merge_validator
        result = merge_validator.fast_track_check("nonexistent-task-id")
        self.assertFalse(result)


class TestValidateDraftDisabled(unittest.TestCase):
    @patch.dict(os.environ, {"ORCH_MERGE_VALIDATOR_ENABLED": "false"})
    def test_returns_invalid_when_disabled(self):
        import importlib, merge_validator
        importlib.reload(merge_validator)
        result = merge_validator.validate_draft(
            {"id": "t1"}, "diff content", "/tmp", "main", "echo ok")
        self.assertFalse(result["valid"])
        importlib.reload(merge_validator)


if __name__ == "__main__":
    unittest.main()
