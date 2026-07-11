"""Tests for prompt_compressor — prompt compression pipeline."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import prompt_compressor


class TestCompress(unittest.TestCase):
    def test_compress_returns_dict(self):
        result = prompt_compressor.compress("short prompt", "")
        self.assertIsInstance(result, dict)
        for key in ("prompt", "extras", "savings"):
            self.assertIn(key, result)

    def test_no_reduction_on_short(self):
        result = prompt_compressor.compress("short prompt", "")
        savings = result.get("savings", {})
        reduction = savings.get("reduction_pct", 0)
        self.assertAlmostEqual(reduction, 0, delta=1)


class TestMeasure(unittest.TestCase):
    def test_measure_counts(self):
        result = prompt_compressor.measure("hello world", "")
        self.assertIsInstance(result, dict)
        self.assertIn("total_chars", result)
        self.assertIn("estimated_tokens", result)


class TestPromptCompressorStats(unittest.TestCase):
    def test_stats_returns_dict(self):
        result = prompt_compressor.stats()
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
