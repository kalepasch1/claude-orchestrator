import json
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
        # db.update(table, match, patch) -- index 1 is the MATCH, which is
        # {"id": "t1"} and never contains finished_at. The test was reading the
        # wrong positional argument, not finding a defect in transition().
        table, match, call_patch = mock_update.call_args[0]
        self.assertEqual(table, "tasks")
        self.assertEqual(match, {"id": "t1"})
        self.assertIn("finished_at", call_patch)
        self.assertEqual(call_patch["state"], "DONE")


class TaskNotFoundTest(unittest.TestCase):
    def test_raises_on_missing_task(self):
        with patch.object(api.db, "select", return_value=[]):
            with self.assertRaises(api.TaskNotFoundError):
                api.get_task("nonexistent")


class QueueStatsTest(unittest.TestCase):
    """These mocked db.sql, which db does not have.

    patch.object(api.db, "sql", ...) raises AttributeError before the test body
    runs, so neither of these ever exercised queue_stats. Underneath, the
    function really did call db.sql and really did return {} every time -- a
    queue-stats endpoint that has only ever reported an empty queue.
    """

    QUEUED = 10
    RUNNING = 3

    def _rows(self):
        return ([{"state": "QUEUED"}] * self.QUEUED
                + [{"state": "RUNNING"}] * self.RUNNING)

    def test_returns_dict_of_state_counts(self):
        with patch.object(api.db, "select_all", return_value=self._rows()):
            result = api.queue_stats()
        self.assertEqual(result["QUEUED"], self.QUEUED)
        self.assertEqual(result["RUNNING"], self.RUNNING)

    def test_returns_empty_on_error(self):
        with patch.object(api.db, "select_all", side_effect=Exception("db down")):
            result = api.queue_stats()
        self.assertEqual(result, {})

    def test_only_the_state_column_is_read(self):
        """A stats call must not drag every column of every task across."""
        captured = {}

        def fake(table, params=None, **kw):
            captured["table"] = table
            captured["params"] = dict(params or {})
            return []

        with patch.object(api.db, "select_all", side_effect=fake):
            api.queue_stats()

        self.assertEqual(captured["table"], "tasks")
        self.assertEqual(captured["params"]["select"], "state")

    def test_a_state_outside_valid_transitions_is_still_counted(self):
        """The old SQL counted whatever existed; the replacement must too."""
        rows = [{"state": "DEPLOYED_AND_VERIFIED"}, {"state": "RETRY"}]
        with patch.object(api.db, "select_all", return_value=rows):
            result = api.queue_stats()
        self.assertEqual(result, {"DEPLOYED_AND_VERIFIED": 1, "RETRY": 1})


class ProjectStatsTest(unittest.TestCase):
    def test_the_project_filter_carries_a_postgrest_operator(self):
        """A bare value is a 400, which the fail-soft handler would hide as {}."""
        captured = {}

        def fake(table, params=None, **kw):
            captured.update(params or {})
            return [{"state": "QUEUED"}]

        with patch.object(api.db, "select_all", side_effect=fake):
            result = api.project_stats("p1")

        self.assertEqual(captured["project_id"], "eq.p1")
        self.assertEqual(result, {"QUEUED": 1})


class HeartbeatTest(unittest.TestCase):
    """heartbeat() sent `INSERT ... ON CONFLICT` through db.sql.

    So no executor using this API has ever recorded a heartbeat, and the bare
    `except Exception: pass` meant nobody found out.
    """

    def test_it_upserts_into_fleet_config(self):
        with patch.object(api.db, "insert") as mock_insert:
            api.heartbeat("mac-lan", claimed=2, done=1)

        table, row = mock_insert.call_args[0]
        self.assertEqual(table, "fleet_config")
        self.assertEqual(row["key"], "mac-lan_LAST_RUN")
        self.assertTrue(mock_insert.call_args[1]["upsert"],
                        "without upsert the second heartbeat is a duplicate-key error")

        payload = json.loads(row["value"])
        self.assertEqual(payload["claimed"], 2)
        self.assertEqual(payload["done"], 1)
        self.assertTrue(payload["ts"].endswith("Z"))

    def test_a_write_failure_is_still_swallowed(self):
        """Fail-soft is right for a heartbeat -- it just must not be the only path."""
        with patch.object(api.db, "insert", side_effect=Exception("db down")):
            self.assertIsNone(api.heartbeat("mac-lan"))


if __name__ == "__main__":
    unittest.main()
