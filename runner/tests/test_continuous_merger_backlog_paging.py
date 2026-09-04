#!/usr/bin/env python3
"""merge_backlog is the safety net under the immediate on_task_done merge path.

It must see EVERY DONE row. It used to call db.select with no limit and no order;
PostgREST caps a response at 1,000 rows, so once there were more DONE tasks than
that (1,135 when this was found) the sweep saw a 1,000-row slice in server-chosen
order, and a branch outside the slice was never swept at all however long it waited.

Same defect and same fix as db._done_slugs, where `limit: "10000"` looked generous
and 74% of completions were invisible until it paged to exhaustion.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import continuous_merger as cm


def _rows(n, start=0):
    return [{"id": f"t{i}", "slug": f"slug-{i}", "project_id": "p1", "state": "DONE"}
            for i in range(start, start + n)]


class BacklogSweepSeesEveryDoneTask(unittest.TestCase):

    def setUp(self):
        self.submitted = []
        patcher = mock.patch.object(cm, "on_task_done", self.submitted.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        enabled = mock.patch.object(cm, "ENABLED", True)
        enabled.start()
        self.addCleanup(enabled.stop)

    def test_it_pages_rather_than_taking_the_first_response(self):
        """The regression: 1,135 DONE rows must all be swept, not the first 1,000."""
        rows = _rows(1135)
        with mock.patch.object(cm.db, "select_all", return_value=rows) as select_all:
            out = cm.merge_backlog()
        select_all.assert_called_once()
        self.assertEqual(out["swept"], 1135)
        self.assertEqual(len(self.submitted), 1135)

    def test_it_does_not_use_the_capped_single_page_select(self):
        """db.select is subject to the 1,000-row cap; select_all is not."""
        with mock.patch.object(cm.db, "select_all", return_value=_rows(3)), \
             mock.patch.object(cm.db, "select") as capped:
            cm.merge_backlog()
        capped.assert_not_called()

    def test_the_sweep_is_deterministic_and_fifo(self):
        """Without an explicit order the row set is server-chosen, so which branches
        get swept can change between passes for no reason a human can see."""
        with mock.patch.object(cm.db, "select_all", return_value=_rows(2)) as select_all:
            cm.merge_backlog()
        self.assertEqual(select_all.call_args.kwargs.get("order"), "created_at.asc")

    def test_a_project_filter_is_still_applied(self):
        with mock.patch.object(cm.db, "select_all", return_value=_rows(1)) as select_all:
            cm.merge_backlog(project_id="p9")
        filters = select_all.call_args.args[1]
        self.assertEqual(filters["state"], "eq.DONE")
        self.assertEqual(filters["project_id"], "eq.p9")

    def test_a_query_failure_is_reported_not_reported_as_empty(self):
        """A sweep returning 0 because the DB errored must not read as 'nothing to
        merge'. That is how a stalled merge queue looks healthy."""
        with mock.patch.object(cm.db, "select_all", side_effect=RuntimeError("db down")):
            out = cm.merge_backlog()
        self.assertEqual(out["swept"], 0)
        self.assertIn("db down", out.get("error", ""))
        self.assertEqual(self.submitted, [])

    def test_a_disabled_merger_sweeps_nothing(self):
        with mock.patch.object(cm, "ENABLED", False):
            out = cm.merge_backlog()
        self.assertEqual(out["swept"], 0)
        self.assertEqual(self.submitted, [])

    def test_an_empty_backlog_is_not_an_error(self):
        with mock.patch.object(cm.db, "select_all", return_value=[]):
            out = cm.merge_backlog()
        self.assertEqual(out["swept"], 0)
        self.assertNotIn("error", out)


if __name__ == "__main__":
    unittest.main()
