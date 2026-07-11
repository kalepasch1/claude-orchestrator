"""Tests for task_fusion — task cluster identification and merging."""
import unittest
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestFileScope(unittest.TestCase):
    def test_extracts_python_paths(self):
        import task_fusion
        t = {"prompt": "Fix the bug in runner/db.py and update runner/runner.py"}
        files = task_fusion._extract_file_scope(t)
        self.assertIn("runner/db.py", files)
        self.assertIn("runner/runner.py", files)

    def test_empty_prompt_returns_empty_set(self):
        import task_fusion
        files = task_fusion._extract_file_scope({"prompt": ""})
        self.assertEqual(files, set())

    def test_no_prompt_returns_empty_set(self):
        import task_fusion
        files = task_fusion._extract_file_scope({})
        self.assertEqual(files, set())


class TestComputeOverlap(unittest.TestCase):
    def test_identical_sets(self):
        import task_fusion
        overlap = task_fusion._compute_overlap({"a.py", "b.py"}, {"a.py", "b.py"})
        self.assertAlmostEqual(overlap, 1.0)

    def test_disjoint_sets(self):
        import task_fusion
        overlap = task_fusion._compute_overlap({"a.py"}, {"b.py"})
        self.assertAlmostEqual(overlap, 0.0)

    def test_partial_overlap(self):
        import task_fusion
        overlap = task_fusion._compute_overlap({"a.py", "b.py"}, {"b.py", "c.py"})
        self.assertAlmostEqual(overlap, 1/3)  # intersection=1, union=3

    def test_empty_sets(self):
        import task_fusion
        overlap = task_fusion._compute_overlap(set(), set())
        self.assertAlmostEqual(overlap, 0.0)


class TestBuildFusedPrompt(unittest.TestCase):
    def test_combines_prompts(self):
        import task_fusion
        tasks = [
            {"slug": "fix-a", "prompt": "Fix bug A"},
            {"slug": "fix-b", "prompt": "Fix bug B"},
        ]
        result = task_fusion._build_fused_prompt(tasks)
        self.assertIn("fix-a", result)
        self.assertIn("fix-b", result)
        self.assertIn("Fix bug A", result)
        self.assertIn("Fix bug B", result)
        self.assertIn("fused", result.lower())


class TestStats(unittest.TestCase):
    def test_returns_dict(self):
        import task_fusion
        s = task_fusion.stats()
        self.assertIsInstance(s, dict)
        self.assertIn("scans", s)


class TestScanDisabledByDefault(unittest.TestCase):
    def test_scan_returns_empty_when_disabled(self):
        import task_fusion
        # Default is ORCH_TASK_FUSION_ENABLED=false
        result = task_fusion.scan_and_fuse()
        self.assertEqual(result.get("fused_clusters", 0), 0)


if __name__ == "__main__":
    unittest.main()
