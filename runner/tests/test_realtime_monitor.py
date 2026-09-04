#!/usr/bin/env python3
"""Real-time monitoring: slice 3, the tests the module never had.

`realtime_monitor` powers the ops dashboard and had no test file at all. Writing them
surfaced two defects, both of which make the dashboard lie in the direction of calm:

1. COUNT BY FETCH. `_throughput` selected rows and returned len(). PostgREST caps a
   response at 1000 rows whatever the query asks for, so throughput SATURATED at 1000 —
   past that the number stopped moving, and the 24h window hit the ceiling long before
   the 1h window did, so 24h could read LOWER than 1h. Now db.count, which asks the
   server for the exact number and transfers no rows.

2. OUTAGE RENDERED AS ZERO. Every collector swallowed exceptions and returned 0 / {} / [].
   On a monitoring surface that is the worst possible default: a control-plane outage and
   a fleet that did nothing produce an identical reading, so the dashboard is calmest
   exactly when it should be loudest. Collectors now return None (UNKNOWN) and `snapshot`
   publishes a `degraded` list plus an `ok` flag.

Proof: python3 -m pytest runner/tests/test_realtime_monitor.py -q
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import realtime_monitor as rm  # noqa: E402


class _DB:
    """A db seam with no database."""

    def __init__(self, count=None, sql_rows=None, rows=None, boom=False):
        self._count = count
        self._sql_rows = sql_rows if sql_rows is not None else []
        self._rows = rows if rows is not None else []
        self.boom = boom
        self.count_calls = []
        self.select_calls = []

    def count(self, table, params=None):
        if self.boom:
            raise RuntimeError("control plane down")
        self.count_calls.append((table, params))
        return self._count

    def sql(self, query):
        if self.boom:
            raise RuntimeError("control plane down")
        return self._sql_rows

    def select(self, table, params=None):
        if self.boom:
            raise RuntimeError("control plane down")
        self.select_calls.append((table, params))
        return self._rows

    def insert(self, table, row):
        if self.boom:
            raise RuntimeError("control plane down")
        return row


def _with_db(db):
    return patch.dict(sys.modules, {"db": db})


def _reset_cache():
    with rm._lock:
        rm._STATE["last_snapshot"] = None
        rm._STATE["snapshot_at"] = None


class TestThroughput(unittest.TestCase):
    def setUp(self):
        _reset_cache()

    def test_it_asks_the_server_for_a_count(self):
        db = _DB(count=4213)
        with _with_db(db):
            self.assertEqual(rm._throughput(1), 4213)
        self.assertEqual(db.count_calls[0][0], "tasks")

    def test_it_does_not_saturate_at_the_page_cap(self):
        """The reported defect: a fetch-and-len throughput froze at 1000."""
        with _with_db(_DB(count=25000)):
            self.assertEqual(rm._throughput(24), 25000)

    def test_it_never_fetches_rows_to_count_them(self):
        db = _DB(count=7)
        with _with_db(db):
            rm._throughput(1)
        self.assertEqual(db.select_calls, [], "throughput fetched rows to count them")

    def test_the_window_is_passed_to_the_server(self):
        db = _DB(count=1)
        with _with_db(db):
            rm._throughput(24)
        params = db.count_calls[0][1]
        self.assertIn("updated_at", params)
        self.assertTrue(params["updated_at"].startswith("gte."))

    def test_a_wider_window_is_an_earlier_cutoff(self):
        db = _DB(count=1)
        with _with_db(db):
            rm._throughput(1)
            rm._throughput(24)
        self.assertLess(db.count_calls[1][1]["updated_at"],
                        db.count_calls[0][1]["updated_at"])

    def test_an_outage_is_unknown_not_zero(self):
        with _with_db(_DB(boom=True)):
            self.assertIsNone(rm._throughput(1))

    def test_a_genuine_zero_is_still_zero(self):
        with _with_db(_DB(count=0)):
            self.assertEqual(rm._throughput(1), 0)


class TestCollectorsReportUnknown(unittest.TestCase):
    def setUp(self):
        _reset_cache()

    def test_queue_depths_unknown_on_outage(self):
        with _with_db(_DB(boom=True)):
            self.assertIsNone(rm._queue_depths())

    def test_queue_depths_empty_when_genuinely_empty(self):
        with _with_db(_DB(sql_rows=[])):
            self.assertEqual(rm._queue_depths(), {})

    def test_pending_approvals_unknown_on_outage(self):
        with _with_db(_DB(boom=True)):
            self.assertIsNone(rm._pending_approvals())

    def test_project_summary_unknown_on_outage(self):
        with _with_db(_DB(boom=True)):
            self.assertIsNone(rm._project_summary())

    def test_approval_queue_still_returns_a_list_for_the_widget(self):
        with _with_db(_DB(boom=True)):
            self.assertEqual(rm.approval_queue(), [])


class TestSnapshot(unittest.TestCase):
    def setUp(self):
        _reset_cache()

    def _healthy(self):
        return _DB(count=12,
                   sql_rows=[{"state": "QUEUED", "cnt": 3}, {"state": "DONE", "cnt": 2}],
                   rows=[{"slug": "s1", "kind": "build", "project_id": "p",
                          "note": "x", "updated_at": "2026-08-24T00:00:00Z"}])

    def test_a_healthy_snapshot_is_ok_with_nothing_degraded(self):
        with _with_db(self._healthy()):
            snap = rm.snapshot()
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["degraded"], [])

    def test_a_healthy_snapshot_totals_its_depths(self):
        with _with_db(self._healthy()):
            snap = rm.snapshot()
        self.assertEqual(snap["total_tasks"], 5)
        self.assertEqual(snap["pending_count"], 1)

    def test_an_outage_snapshot_is_not_ok(self):
        with _with_db(_DB(boom=True)):
            snap = rm.snapshot()
        self.assertFalse(snap["ok"])

    def test_an_outage_names_every_metric_it_could_not_measure(self):
        with _with_db(_DB(boom=True)):
            snap = rm.snapshot()
        for name in ("queue_depths", "throughput_1h", "throughput_24h",
                     "pending_count", "project_summary"):
            self.assertIn(name, snap["degraded"], name)

    def test_an_outage_does_not_report_zero_throughput(self):
        with _with_db(_DB(boom=True)):
            snap = rm.snapshot()
        self.assertIsNone(snap["throughput_1h"])
        self.assertIsNone(snap["total_tasks"])

    def test_an_empty_but_reachable_fleet_is_ok_and_totals_zero(self):
        """The distinction the whole change exists to make."""
        with _with_db(_DB(count=0, sql_rows=[], rows=[])):
            snap = rm.snapshot()
        self.assertTrue(snap["ok"], snap["degraded"])
        self.assertEqual(snap["total_tasks"], 0)
        self.assertEqual(snap["throughput_1h"], 0)

    def test_collection_shapes_stay_iterable_for_the_dashboard(self):
        with _with_db(_DB(boom=True)):
            snap = rm.snapshot()
        self.assertIsInstance(snap["queue_depths"], dict)
        self.assertIsInstance(snap["pending_approvals"], list)

    def test_the_ttl_cache_is_used(self):
        db = self._healthy()
        with _with_db(db):
            rm.snapshot()
            calls = len(db.count_calls)
            rm.snapshot()
        self.assertEqual(len(db.count_calls), calls, "TTL cache was bypassed")

    def test_stats_reports_the_snapshot_count(self):
        with _with_db(self._healthy()):
            before = rm.stats()["snapshot_count"]
            rm.snapshot()
        self.assertEqual(rm.stats()["snapshot_count"], before + 1)


class TestRun(unittest.TestCase):
    def setUp(self):
        _reset_cache()

    def test_run_returns_the_snapshot(self):
        db = _DB(count=1, sql_rows=[{"state": "DONE", "cnt": 1}], rows=[])
        with _with_db(db):
            snap = rm.run()
        self.assertIn("snapshot_at", snap)

    def test_a_degraded_run_says_so_in_the_inbox_title(self):
        written = {}

        class _Rec(_DB):
            def insert(self, table, row):
                written.update(row)
                return row

        db = _Rec(boom=False, count=None, sql_rows=None, rows=None)
        db._count = None
        with _with_db(db):
            snap = rm.snapshot()
            # force the degraded shape without breaking the insert itself
            snap["ok"] = False
            snap["degraded"] = ["throughput_1h"]
            snap["throughput_1h"] = None
            with patch.object(rm, "snapshot", return_value=snap):
                rm.run()
        self.assertIn("DEGRADED", written.get("title", ""))
        self.assertIn("unknown", written.get("title", ""))

    def test_run_never_raises_when_the_inbox_write_fails(self):
        with _with_db(_DB(boom=True)):
            rm.run()


if __name__ == "__main__":
    unittest.main()
