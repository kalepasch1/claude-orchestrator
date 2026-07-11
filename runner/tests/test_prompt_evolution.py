"""Tests for prompt_evolution — self-improving prompt evolution."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub db before importing the module
fake_db = MagicMock()
fake_db.select.return_value = []
fake_db.insert.return_value = None
with patch.dict(sys.modules, {"db": fake_db}):
    import prompt_evolution


class TestPromptEvolutionStats(unittest.TestCase):
    def test_stats_returns_dict(self):
        result = prompt_evolution.stats()
        self.assertIsInstance(result, dict)


class TestGetEvolvedAdditions(unittest.TestCase):
    def test_get_evolved_additions_empty(self):
        with patch.object(prompt_evolution, "db") as mdb:
            mdb.select.return_value = []
            result = prompt_evolution.get_evolved_additions({}, "test")
            # With no data, should return empty string or None
            self.assertFalse(result)  # empty string or None are both falsy


class TestRecordPromptOutcome(unittest.TestCase):
    def test_record_no_raise(self):
        with patch.object(prompt_evolution, "db") as mdb:
            mdb.insert.return_value = None
            # Should not raise
            prompt_evolution.record_prompt_outcome(
                {"slug": "test-task"}, "prompt text", "claude-sonnet",
                True, 0.05, 1
            )


if __name__ == "__main__":
    unittest.main()
