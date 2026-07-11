"""Tests for pattern_adversary — adversarial self-testing for patterns."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pattern_adversary


class TestPatternAdversaryStats(unittest.TestCase):
    def test_stats_returns_dict(self):
        result = pattern_adversary.stats()
        self.assertIsInstance(result, dict)
        self.assertIn("patterns_tested", result)


class TestTestPattern(unittest.TestCase):
    def test_test_pattern_empty(self):
        result = pattern_adversary.test_pattern("p1", {})
        self.assertIsInstance(result, dict)
        self.assertIn("verdict", result)
        # Empty pattern data should yield "uncertain"
        self.assertEqual(result["verdict"], "uncertain")


class TestRecordRealOutcome(unittest.TestCase):
    def test_record_real_outcome_no_raise(self):
        # Should not raise on any input
        pattern_adversary.record_real_outcome("p1", True)


if __name__ == "__main__":
    unittest.main()
