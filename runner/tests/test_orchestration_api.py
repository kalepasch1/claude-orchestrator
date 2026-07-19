import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestration_api as api


class ValidTransitionsTest(unittest.TestCase):
    def test_queued_can_transition_to_running(self):
        self.assertIn("RUNNING", api.VALID_TRANSITIONS["QUEUED"])

    def test_merged_is_terminal(self):
        self.assertEqual(api.VALID_TRANSITIONS["MERGED"], set())

    def test_running_can_go_back_to_queued(self):
        self.assertIn("QUEUED", api.VALID_TRANSITIONS["RUNNING"])

    def test_blocked_can_be_requeued(self):
        self.assertIn("QUEUED", api.VALID_TRANSITIONS["BLOCKED"])


class TransitionValidationTest(unittest.TestCase):
    def test_invalid_transition_raises(self):
        with patch.object(api, "get_task", return_value={"id": "t1", "state": "MERGED"}):
            with self.assertRaises(api.InvalidTransitionError):
                api.transition("t1", "QUEUED")

    def test_valid_transition_calls_update(self):
        with patch.object(api, "get_task", return_value={"id": "t1", "state": "QUEUED"}), \
             patch.object(api.db, "update") as mock_update:
            result = api.transition("t1", "RUNNING", account="test")
        mock_update.assert_called_once()
        self.assertEqual(result["state"], "RUNNING")

    def test_done_transition_sets_finished_at(self):
        with patch.object(api, "get_task", return_value={"id": "t1", "state": "RUNNING"}), \
             patch.object(api.db, "update") as mock_update:
            api.transition("t1", "DONE")
        call_patch = mock_update.call_args[0][1]
        self.assertIn("finished_at", call_patch)


class TaskNotFoundTest(unittest.TestCase):
    def test_raises_on_missing_task(self):
        with patch.object(api.db, "select", return_value=[]):
            with self.assertRaises(api.TaskNotFoundError):
                api.get_task("nonexistent")


class QueueStatsTest(unittest.TestCase):
    def test_returns_dict_of_state_counts(self):
        mock_rows = [
            {"state": "QUEUED", "cnt": 10},
            {"state": "RUNNING", "cnt": 3},
        ]
        with patch.object(api.db, "sql", return_value=mock_rows):
            result = api.queue_stats()
        self.assertEqual(result["QUEUED"], 10)
        self.assertEqual(result["RUNNING"], 3)

    def test_returns_empty_on_error(self):
        with patch.object(api.db, "sql", side_effect=Exception("db down")):
            result = api.queue_stats()
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
