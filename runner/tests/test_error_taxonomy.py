"""Tests for error_taxonomy — error classification and remediation."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import error_taxonomy


class TestClassify(unittest.TestCase):
    def test_classify_rate_limit(self):
        result = error_taxonomy.classify("Rate limit exceeded")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["error_class"], "rate_limit")

    def test_classify_test_failure(self):
        result = error_taxonomy.classify("FAILED test_auth")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["error_class"], "test_failure")

    def test_classify_unknown(self):
        result = error_taxonomy.classify("some random error")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["error_class"], "unknown")


class TestRemediationPrompt(unittest.TestCase):
    def test_remediation_prompt_test_failure(self):
        result = error_taxonomy.remediation_prompt("test_failure", "FAILED test_auth")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


class TestErrorTaxonomyStats(unittest.TestCase):
    def test_stats_returns_dict(self):
        result = error_taxonomy.stats()
        self.assertIsInstance(result, dict)
        for key in ("error_distribution", "remediation_success_rates"):
            self.assertIn(key, result)


if __name__ == "__main__":
    unittest.main()
