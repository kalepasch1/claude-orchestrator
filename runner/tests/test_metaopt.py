"""metaopt must read the queue it is tuning for.

What this file used to be
-------------------------
Four tests against `metaopt.recommend_cadence()`, returning `poll_interval_sec`
and `queue_depth`, over a fake db module exposing `db.sql(query)`. None of those
three names has ever existed: the module's function is `recommend()`, its keys
are `poll_interval_s` and `queued`, and db speaks PostgREST -- there has never
been a raw-SQL channel on it. The tests could only ever raise AttributeError,
and the fake db they installed intercepted nothing.

What replaces them
------------------
The defect underneath. _recent_queue_stats() and _throughput_last_window() sent
raw SQL through db.query() inside bare `except Exception` handlers, so both
returned zero on every call regardless of the queue. recommend() saw pressure 0
forever and took the idle branch forever -- MAX_POLL_S and MIN_PARALLEL -- and
apply() wrote that to fleet_config as though it were a measurement. Measured on
a live queue of 322 pending tasks, the old code reported "idle (0 pending)" and
recommended poll=120s parallel=1; the fixed code reports 321 queued / 1 running
and recommends poll=10s parallel=8.

runner/test_metaopt.py (a different file) already covers recommend()'s
thresholds with both readers mocked. These tests are about the readers.
"""
import ast
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import metaopt

QUEUED = 40
RUNNING = 2
VERIFIED = 7
BUSY_QUEUE = 321
BUSY_RUNNING = 1
MERGED_WITH_EVIDENCE = 2
HALF = 0.5


class TheReadersActuallyRead(unittest.TestCase):
    def test_queue_stats_come_back_as_the_counts_the_database_gave(self):
        seen = []

        def fake_count(table, params=None):
            seen.append((table, dict(params or {})))
            return {"eq.QUEUED": QUEUED, "eq.RUNNING": RUNNING,
                    "eq.DEPLOYED_AND_VERIFIED": VERIFIED}[params["state"]]

        with patch.object(metaopt.db, "count", side_effect=fake_count):
            queued, running, done = metaopt._recent_queue_stats()

        self.assertEqual((queued, running, done), (QUEUED, RUNNING, VERIFIED))
        self.assertEqual([t for t, _ in seen], ["tasks"] * len(seen))

    def test_the_filters_carry_a_postgrest_operator(self):
        """A bare value is a 400, which the fail-soft handler would hide as 0."""
        seen = []

        def fake_count(table, params=None):
            seen.append(dict(params or {}))
            return 0

        with patch.object(metaopt.db, "count", side_effect=fake_count):
            metaopt._recent_queue_stats()

        self.assertTrue(seen)
        for params in seen:
            self.assertTrue(params["state"].startswith("eq."), params)

    def test_a_read_failure_is_zero_and_not_an_exception(self):
        """Fail-soft is still right here -- it just must not be the only path."""
        with patch.object(metaopt.db, "count", side_effect=RuntimeError("down")):
            self.assertEqual(metaopt._recent_queue_stats(), (0, 0, 0))

    def test_throughput_counts_verified_fully_and_merged_at_half(self):
        """REWARD HYGIENE: MERGED counts 0.5, and only with artifact_commit."""
        merged_rows = [
            {"id": "a", "artifact_commit": "abc123"},
            {"id": "b", "artifact_commit": "def456"},
            {"id": "c", "artifact_commit": ""},        # no evidence -> ignored
            {"id": "d", "artifact_commit": None},      # no evidence -> ignored
            {"id": "e"},                               # no column  -> ignored
        ]
        with patch.object(metaopt.db, "count", return_value=VERIFIED):
            with patch.object(metaopt.db, "select_all", return_value=merged_rows):
                total = metaopt._throughput_last_window()

        self.assertEqual(total, int(VERIFIED + HALF * MERGED_WITH_EVIDENCE))

    def test_throughput_windows_both_halves_on_updated_at(self):
        captured = {}

        def fake_count(table, params=None):
            captured["count"] = dict(params or {})
            return 0

        def fake_select_all(table, params=None, **kw):
            captured["select_all"] = dict(params or {})
            return []

        with patch.object(metaopt.db, "count", side_effect=fake_count):
            with patch.object(metaopt.db, "select_all", side_effect=fake_select_all):
                metaopt._throughput_last_window()

        for key in ("count", "select_all"):
            self.assertTrue(captured[key]["updated_at"].startswith("gte."), key)


class APendingQueueIsNeverReportedAsIdle(unittest.TestCase):
    """The end-to-end shape of the bug: real pressure, idle recommendation."""

    def test_a_busy_queue_produces_the_high_pressure_branch(self):
        def fake_count(table, params=None):
            return {"eq.QUEUED": BUSY_QUEUE, "eq.RUNNING": BUSY_RUNNING,
                    "eq.DEPLOYED_AND_VERIFIED": 0}[params["state"]]

        with patch.object(metaopt.db, "count", side_effect=fake_count):
            with patch.object(metaopt.db, "select_all", return_value=[]):
                rec = metaopt.recommend()

        self.assertEqual(rec["queued"], BUSY_QUEUE)
        self.assertEqual(rec["poll_interval_s"], metaopt.MIN_POLL_S)
        self.assertEqual(rec["max_parallel"], metaopt.MAX_PARALLEL)
        self.assertIn("high pressure", rec["reason"])
        self.assertNotIn("idle", rec["reason"])

    def test_apply_dry_run_writes_nothing(self):
        with patch.object(metaopt.db, "count", return_value=0):
            with patch.object(metaopt.db, "select_all", return_value=[]):
                with patch.object(metaopt.db, "insert") as mock_insert:
                    rec = metaopt.apply(dry_run=True)
        self.assertFalse(rec["applied"])
        self.assertFalse(mock_insert.called)


class NoRawSqlChannel(unittest.TestCase):
    def test_metaopt_does_not_reach_for_db_query_or_db_sql(self):
        """db has neither. Both calls sat inside handlers that hid the failure.

        AST, not a substring search: the docstrings above quote the old
        `db.query(...)` line verbatim to say what was wrong with it, and a
        grep-shaped test would fail on its own explanation. Only real call sites
        count.
        """
        with open(metaopt.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())

        called = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "db"):
                called.add(func.attr)

        self.assertNotIn("query", called)
        self.assertNotIn("sql", called)
        self.assertTrue(called, "metaopt should still be talking to db somehow")

    def test_db_really_has_no_such_functions(self):
        """If one is ever added, this test is the place to reconsider the above."""
        self.assertFalse(hasattr(metaopt.db, "query"))
        self.assertFalse(hasattr(metaopt.db, "sql"))


if __name__ == "__main__":
    unittest.main()
