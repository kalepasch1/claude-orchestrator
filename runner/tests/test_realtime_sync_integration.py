#!/usr/bin/env python3
"""
Tests for the runner-side half of the real-time sync channel.

Two defects are covered here, both of the "written but never reachable" kind
this repo keeps producing:

  1. realtime_sync had no single-pass entry point, so a short-lived
     `periodic.py <job>` invocation could not drive it. Zero callers.
  2. periodic.run_rtmon existed but was absent from JOBS, so the CLI rejected
     `periodic.py rtmon` as an unknown job. Unreachable.
"""
import os
import sys
import unittest
from unittest import mock

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import realtime_sync  # noqa: E402


class PollOnceTest(unittest.TestCase):
    def setUp(self):
        realtime_sync.reset_watermarks()
        self._prev_enabled = realtime_sync.ENABLED
        realtime_sync.ENABLED = True
        # Drop handlers left by other tests.
        realtime_sync._handlers.clear()

    def tearDown(self):
        realtime_sync.ENABLED = self._prev_enabled
        realtime_sync._handlers.clear()
        realtime_sync.reset_watermarks()

    def test_poll_once_exists_and_is_callable(self):
        self.assertTrue(callable(getattr(realtime_sync, "poll_once", None)))

    def test_poll_once_returns_per_table_counts(self):
        rows = [{"id": "1", "slug": "a", "state": "DONE", "updated_at": "2026-08-12T00:00:00Z"}]
        with mock.patch.object(realtime_sync.db, "select", return_value=rows):
            out = realtime_sync.poll_once()
        self.assertEqual(set(out), set(realtime_sync._WATCHED))
        self.assertEqual(out["tasks"], 1)

    def test_poll_once_dispatches_to_registered_handlers(self):
        seen = []
        realtime_sync.register("tasks", lambda r: seen.append(r))
        rows = [{"id": "1", "updated_at": "2026-08-12T00:00:00Z"}]
        with mock.patch.object(realtime_sync.db, "select", return_value=rows):
            realtime_sync.poll_once()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0], rows)

    def test_poll_once_advances_the_watermark(self):
        rows = [{"id": "1", "updated_at": "2026-08-12T00:00:00Z"}]
        with mock.patch.object(realtime_sync.db, "select", return_value=rows) as sel:
            realtime_sync.poll_once()
            realtime_sync.poll_once()
        # Second pass must filter on the watermark from the first.
        last_query = sel.call_args_list[-1][0][1]
        self.assertEqual(last_query.get("updated_at"), "gt.2026-08-12T00:00:00Z")

    def test_poll_once_is_fail_soft_when_the_db_raises(self):
        with mock.patch.object(realtime_sync.db, "select", side_effect=RuntimeError("boom")):
            out = realtime_sync.poll_once()  # must not raise
        self.assertEqual(out.get("tasks"), 0)

    def test_poll_once_is_fail_soft_when_a_handler_raises(self):
        def bad(_rows):
            raise ValueError("handler exploded")

        realtime_sync.register("tasks", bad)
        rows = [{"id": "1", "updated_at": "2026-08-12T00:00:00Z"}]
        before = realtime_sync.stats()["handler_errors"]
        with mock.patch.object(realtime_sync.db, "select", return_value=rows):
            realtime_sync.poll_once()  # must not raise
        self.assertGreater(realtime_sync.stats()["handler_errors"], before)

    def test_poll_once_is_a_no_op_when_disabled(self):
        realtime_sync.ENABLED = False
        with mock.patch.object(realtime_sync.db, "select") as sel:
            self.assertEqual(realtime_sync.poll_once(), {})
        sel.assert_not_called()

    def test_reset_watermarks_clears_state(self):
        realtime_sync._watermarks["tasks"] = "2026-01-01T00:00:00Z"
        realtime_sync.reset_watermarks()
        self.assertEqual(realtime_sync._watermarks, {})


class RtmonJobRegistrationTest(unittest.TestCase):
    """The regression that made the runner half unreachable."""

    def test_rtmon_is_registered_in_JOBS(self):
        import periodic
        self.assertIn("rtmon", periodic.JOBS)
        self.assertIs(periodic.JOBS["rtmon"], periodic.run_rtmon)

    def test_every_run_callable_in_JOBS_is_callable(self):
        import periodic
        for name, fn in periodic.JOBS.items():
            self.assertTrue(callable(fn), f"JOBS[{name!r}] is not callable")

    def test_run_rtmon_survives_all_three_components_failing(self):
        import periodic
        broken = mock.Mock(side_effect=RuntimeError("down"))
        with mock.patch.dict(sys.modules, {
            "realtime_sync": mock.Mock(poll_once=broken),
            "realtime_approval_monitor": mock.Mock(run=broken),
            "realtime_monitor": mock.Mock(run=broken),
        }):
            out = periodic.run_rtmon()  # must not raise
        self.assertIn("sync_error", out)
        self.assertIn("approvals_error", out)
        self.assertIn("monitor_error", out)

    def test_run_rtmon_drains_sync_before_snapshotting(self):
        import periodic
        order = []
        sync = mock.Mock(poll_once=mock.Mock(side_effect=lambda: order.append("sync") or {}))
        monitor = mock.Mock(
            run=mock.Mock(side_effect=lambda: order.append("monitor")),
            stats=mock.Mock(return_value={}),
        )
        with mock.patch.dict(sys.modules, {
            "realtime_sync": sync,
            "realtime_approval_monitor": mock.Mock(run=mock.Mock(return_value={})),
            "realtime_monitor": monitor,
        }):
            periodic.run_rtmon()
        self.assertEqual(order, ["sync", "monitor"])


if __name__ == "__main__":
    unittest.main()
