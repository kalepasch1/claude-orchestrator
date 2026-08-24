"""Tests for retry_budget — adaptive retry budgeting."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub db before importing the module
fake_db = MagicMock()
with patch.dict(sys.modules, {"db": fake_db}):
    import retry_budget


class TestStats(unittest.TestCase):
    def test_stats_returns_dict(self):
        result = retry_budget.stats()
        self.assertIsInstance(result, dict)
        for key in ("total_saved_attempts", "tokens_saved_estimate",
                     "retry_effectiveness", "prefixes_tracked", "enabled",
                     "default_max"):
            self.assertIn(key, result)


class TestErrorClassification(unittest.TestCase):
    def test_transient_provider_errors_are_classified_case_insensitively(self):
        cases = {
            "HTTP 429 Too Many Requests": "rate_limit",
            "CONTEXT DEADLINE EXCEEDED": "timeout",
        }
        for error, expected in cases.items():
            with self.subTest(error=error):
                self.assertEqual(retry_budget._classify_error(error), expected)


class TestMaxAttempts(unittest.TestCase):
    def test_max_attempts_default(self):
        result = retry_budget.max_attempts({})
        self.assertEqual(result, 4)


class TestShouldRetry(unittest.TestCase):
    def test_should_retry_rate_limit(self):
        result = retry_budget.should_retry({}, 1, "rate_limit")
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("retry"))


class TestRecordAttempt(unittest.TestCase):
    def test_record_attempt_no_raise(self):
        # Should not raise on any input
        retry_budget.record_attempt("test-slug", 1, "claude-sonnet", True)


if __name__ == "__main__":
    unittest.main()
