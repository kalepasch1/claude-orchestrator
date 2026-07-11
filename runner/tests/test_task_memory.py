"""Tests for task_memory — individual + hivemind intelligence."""
import unittest
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestStats(unittest.TestCase):
    def test_returns_dict(self):
        import task_memory
        s = task_memory.stats()
        self.assertIsInstance(s, dict)
        self.assertIn("learnings_stored", s)
        self.assertIn("hivemind_queries", s)


class TestInjectHivemind(unittest.TestCase):
    def test_adds_fleet_intelligence_section(self):
        import task_memory
        prompt = "Fix the bug in auth.py"
        insights = {"insights": ["sonnet works best for auth tasks"],
                    "recommended_model": "sonnet", "confidence": 0.8}
        result = task_memory.inject_hivemind(prompt, insights)
        self.assertIn("Fleet Intelligence", result)
        self.assertIn("Fix the bug in auth.py", result)

    def test_empty_insights_returns_original(self):
        import task_memory
        prompt = "Fix the bug"
        result = task_memory.inject_hivemind(prompt, {"insights": []})
        self.assertEqual(result, prompt)


class TestGetDependencyContext(unittest.TestCase):
    def test_no_deps_returns_none(self):
        import task_memory
        result = task_memory.get_dependency_context({"deps": None})
        self.assertIsNone(result)

    def test_empty_deps_returns_none(self):
        import task_memory
        result = task_memory.get_dependency_context({"deps": ""})
        self.assertIsNone(result)


class TestHivemindQueryNoData(unittest.TestCase):
    @patch("db.select")
    def test_returns_empty_with_no_learnings(self, mock_select):
        mock_select.return_value = []
        import task_memory
        result = task_memory.hivemind_query(
            {"slug": "add-field-test", "prompt": "add a field"}, "test-project")
        self.assertIsInstance(result, dict)
        self.assertIn("insights", result)


class TestLearnFromOutcome(unittest.TestCase):
    @patch("db.insert")
    def test_does_not_raise(self, mock_insert):
        mock_insert.return_value = None
        import task_memory
        # Should not raise
        task_memory.learn_from_outcome(
            {"id": "t1", "slug": "fix-bug", "prompt": "fix", "kind": "bugfix"},
            "output text", "claude-sonnet-4-6", 0.05, 30.0, True,
            "claude", "test-project", ["auth.py"])


if __name__ == "__main__":
    unittest.main()
