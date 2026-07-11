"""Tests for conflict_predictor — merge conflict prediction."""
import unittest
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestExtractFiles(unittest.TestCase):
    def test_extracts_python_paths(self):
        import conflict_predictor
        files = conflict_predictor._extract_files("Fix runner/db.py and runner/runner.py")
        self.assertIn("runner/db.py", files)
        self.assertIn("runner/runner.py", files)

    def test_empty_prompt(self):
        import conflict_predictor
        files = conflict_predictor._extract_files("")
        self.assertEqual(files, set())


class TestCheckConflictsDisabled(unittest.TestCase):
    @patch.dict(os.environ, {"ORCH_CONFLICT_PREDICTOR_ENABLED": "false"})
    def test_returns_proceed_when_disabled(self):
        # Reimport to pick up env
        import importlib, conflict_predictor
        importlib.reload(conflict_predictor)
        result = conflict_predictor.check_conflicts({"prompt": "fix db.py"})
        self.assertEqual(result["action"], "proceed")
        # Restore
        importlib.reload(conflict_predictor)


class TestCheckConflictsNoActive(unittest.TestCase):
    @patch("db.select")
    def test_no_active_tasks_proceeds(self, mock_select):
        mock_select.return_value = []
        import conflict_predictor
        result = conflict_predictor.check_conflicts({"prompt": "fix db.py"})
        self.assertEqual(result["action"], "proceed")


class TestStats(unittest.TestCase):
    def test_returns_dict(self):
        import conflict_predictor
        s = conflict_predictor.stats()
        self.assertIsInstance(s, dict)
        self.assertIn("conflicts_detected", s)


class TestSuggestPriority(unittest.TestCase):
    def test_no_conflicts_zero(self):
        import conflict_predictor
        result = conflict_predictor.suggest_priority(
            {"prompt": "fix"}, {"conflicts": [], "action": "proceed"})
        # Returns dict with suggested_priority key, or int 0
        if isinstance(result, dict):
            self.assertEqual(result.get("suggested_priority", 0), 0)
        else:
            self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
