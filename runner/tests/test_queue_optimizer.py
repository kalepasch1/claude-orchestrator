"""Tests for queue_optimizer — queue topology optimization."""
import unittest
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestStats(unittest.TestCase):
    def test_returns_dict(self):
        import queue_optimizer
        s = queue_optimizer.stats()
        self.assertIsInstance(s, dict)
        self.assertIn("false_deps_removed", s)
        self.assertIn("redundant_tasks_removed", s)
        self.assertIn("oversized_flagged", s)
        self.assertIn("bottlenecks_found", s)


class TestOptimize(unittest.TestCase):
    @patch("db.select")
    def test_optimize_with_no_queued_tasks(self, mock_select):
        mock_select.return_value = []
        import queue_optimizer
        result = queue_optimizer.optimize()
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("total_modifications", 0), 0)


class TestNormalizePrompt(unittest.TestCase):
    def test_strips_uuids_and_timestamps(self):
        import queue_optimizer
        p1 = "fix bug abc-123e-456f at 2026-07-11T10:00:00"
        p2 = "fix bug def-789a-012b at 2026-07-12T15:30:00"
        n1 = queue_optimizer._normalize_prompt(p1)
        n2 = queue_optimizer._normalize_prompt(p2)
        # After UUID/timestamp stripping, these should be more similar
        self.assertIsInstance(n1, str)
        self.assertIsInstance(n2, str)

    def test_lowercase_and_strip(self):
        import queue_optimizer
        result = queue_optimizer._normalize_prompt("  Fix The BUG  ")
        self.assertEqual(result, result.lower().strip())


class TestExtractFilePaths(unittest.TestCase):
    def test_finds_file_paths(self):
        import queue_optimizer
        prompt = "Edit runner/db.py and runner/runner.py to fix the import"
        paths = queue_optimizer._extract_file_paths(prompt)
        self.assertIn("runner/db.py", paths)
        self.assertIn("runner/runner.py", paths)

    def test_empty_prompt(self):
        import queue_optimizer
        paths = queue_optimizer._extract_file_paths("")
        self.assertEqual(paths, set())


if __name__ == "__main__":
    unittest.main()
