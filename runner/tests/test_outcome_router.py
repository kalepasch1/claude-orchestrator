"""Tests for outcome_router — outcome-weighted model routing."""
import unittest
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestSlugPrefix(unittest.TestCase):
    def test_extracts_two_segment_prefix(self):
        import outcome_router
        result = outcome_router._slug_prefix("add-field-users-email")
        self.assertEqual(result, "add-field")

    def test_short_slug(self):
        import outcome_router
        result = outcome_router._slug_prefix("fix")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


class TestRecommendNoData(unittest.TestCase):
    def test_falls_back_to_model_router(self):
        import outcome_router
        # With no outcomes data, should fall back to model_router
        result = outcome_router.recommend({"slug": "test-task", "prompt": "fix a bug"}, attempt=1)
        self.assertIn("model", result)
        self.assertIsInstance(result["model"], str)


class TestRecordOutcome(unittest.TestCase):
    def test_record_does_not_raise(self):
        import outcome_router
        # Should never raise
        outcome_router.record_outcome("test-slug", "claude-sonnet-4-6", True)
        outcome_router.record_outcome("test-slug", "claude-sonnet-4-6", False)


class TestStats(unittest.TestCase):
    def test_returns_dict(self):
        import outcome_router
        s = outcome_router.stats()
        self.assertIsInstance(s, dict)
        self.assertIn("routing_decisions", s)


if __name__ == "__main__":
    unittest.main()
