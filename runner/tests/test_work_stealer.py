"""Tests for work_stealer — fleet work stealing."""
import unittest
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestStats(unittest.TestCase):
    def test_returns_dict(self):
        import work_stealer
        s = work_stealer.stats()
        self.assertIsInstance(s, dict)
        self.assertIn("tasks_stolen", s)
        self.assertIn("idle_time_saved_s", s)


class TestShouldStealDisabled(unittest.TestCase):
    def test_disabled_by_default(self):
        import work_stealer
        # Default is ORCH_WORK_STEALING_ENABLED=false
        result = work_stealer.should_steal("runner-1", ["proj-1"])
        self.assertFalse(result)


class TestRecordOutcome(unittest.TestCase):
    def test_does_not_raise(self):
        import work_stealer
        work_stealer.record_stolen_outcome("task-1", True)
        work_stealer.record_stolen_outcome("task-2", False)
        s = work_stealer.stats()
        self.assertGreaterEqual(s["tasks_completed_stolen"], 0)


if __name__ == "__main__":
    unittest.main()
