#!/usr/bin/env python3
"""pipeline_funnel: sentinel timestamps must never become the reported age, and a stage made
entirely of sentinels must never render as empty.

WHY THIS FILE EXISTS
--------------------
46 tasks carry a deliberate pre-2026 `created_at`. They are not corrupt: every claim scan
orders by `created_at ASC`, so an impossible past date pins a task to the front of the queue
forever. The cost lands on the funnel, which reports AGE-OF-OLDEST per stage.

The 2026-08-15 fix walked past sentinels inside a 25-row window. That holds only while a stage
contains fewer than 25 of them. Put 25 sentinels in one state and every visible row is a
sentinel, the skip loop falls through, and the fallback returned the 25th sentinel's age —
58,054.7 hours, 6.6 years, the exact number the fix existed to suppress. It is latent today
because only 2 sentinels are QUEUED. Latent is not fixed; the population that makes it fire is
already in the table.

Everything here is hermetic: no network, no credentials, no clock dependence beyond `now`.
"""
import datetime
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline_funnel as pf  # noqa: E402


SENTINEL = "2020-01-01T00:00:04+00:00"


def _iso(hours_ago):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=hours_ago)).isoformat()


def _server(rows, ts_col="created_at"):
    """A fake PostgREST that honours the range filter, the order and the limit.

    Honouring the filter is the entire point: a stub that ignores it would pass whether or not
    the floor is pushed server-side, which is the bug this file is about.
    """
    def select(table, params):
        cond = str(params.get(ts_col) or "")
        out = [r for r in rows if ts_col in r]
        if cond.startswith("gte."):
            out = [r for r in out if str(r[ts_col]) >= cond[4:]]
        elif cond.startswith("lt."):
            out = [r for r in out if str(r[ts_col]) < cond[3:]]
        out.sort(key=lambda r: str(r[ts_col]),
                 reverse=str(params.get("order") or "").endswith(".desc"))
        try:
            limit = int(params.get("limit") or 0)
        except (TypeError, ValueError):
            limit = 0
        return out[:limit] if limit else out
    return types.SimpleNamespace(select=select)


class _Db:
    def __init__(self, stub):
        self.stub = stub

    def __enter__(self):
        self._real = pf.db
        pf.db = self.stub
        pf._reset_probe_state()
        return self.stub

    def __exit__(self, *exc):
        pf.db = self._real
        return False


class TestSentinelsNeverBecomeTheAnswer(unittest.TestCase):

    def test_one_sentinel_among_real_rows_is_excluded(self):
        rows = [{"created_at": SENTINEL}, {"created_at": _iso(72)}]
        with _Db(_server(rows)):
            age = pf._oldest("tasks", {"state": "eq.QUEUED"}, "created_at", stage="ingest")
        self.assertAlmostEqual(age, 72, delta=1)

    def test_a_full_window_of_sentinels_does_not_report_66_years(self):
        # THE REGRESSION. 30 sentinels > the 25-row window: the old skip loop fell through.
        rows = [{"created_at": SENTINEL} for _ in range(30)]
        with _Db(_server(rows)):
            age = pf._oldest("tasks", {"state": "eq.QUEUED"}, "created_at", stage="ingest")
        self.assertEqual(age, pf.UNMEASURABLE)

    def test_a_full_window_of_sentinels_is_not_reported_as_empty(self):
        rows = [{"created_at": SENTINEL} for _ in range(30)]
        with _Db(_server(rows)):
            age = pf._oldest("tasks", {"state": "eq.QUEUED"}, "created_at", stage="ingest")
        self.assertIsNotNone(age)
        self.assertIn("NOT empty", pf._UNMEASURABLE_WHY["ingest"])

    def test_the_real_row_behind_a_full_window_of_sentinels_is_still_found(self):
        # 30 sentinels plus one genuine 100-hour-old row. Server-side flooring means the
        # window is drawn from real rows only, so the real one is visible.
        rows = [{"created_at": SENTINEL} for _ in range(30)] + [{"created_at": _iso(100)}]
        with _Db(_server(rows)):
            age = pf._oldest("tasks", {"state": "eq.QUEUED"}, "created_at", stage="ingest")
        self.assertAlmostEqual(age, 100, delta=1)

    def test_a_genuinely_empty_stage_returns_none(self):
        with _Db(_server([])):
            age = pf._oldest("tasks", {"state": "eq.DONE"}, "updated_at", stage="card")
        self.assertIsNone(age)

    def test_empty_and_all_sentinel_are_not_the_same_answer(self):
        with _Db(_server([])):
            empty = pf._oldest("tasks", {"state": "eq.QUEUED"}, "created_at", stage="ingest")
        with _Db(_server([{"created_at": SENTINEL}] * 30)):
            pinned = pf._oldest("tasks", {"state": "eq.QUEUED"}, "created_at", stage="ingest")
        self.assertNotEqual(empty, pinned)

    def test_sentinels_are_counted_exactly_not_estimated_from_the_window(self):
        rows = [{"created_at": SENTINEL} for _ in range(46)] + [{"created_at": _iso(10)}]
        with _Db(_server(rows)):
            pf._oldest("tasks", {"state": "eq.QUEUED"}, "created_at", stage="ingest")
        self.assertEqual(pf._SENTINELS["ingest"], 46)


class TestSentinelBookkeepingIsPerStage(unittest.TestCase):
    """`ingest`, `draft` and `card` all read `tasks`. Keyed by table, ingest's sentinel count
    was reported again on draft and card — two stages blamed for rows they do not hold."""

    def test_a_tasks_stage_does_not_inherit_another_tasks_stage_count(self):
        ingest_rows = [{"created_at": SENTINEL}] * 5 + [{"created_at": _iso(50)}]
        with _Db(_server(ingest_rows)):
            pf._oldest("tasks", {"state": "eq.QUEUED"}, "created_at", stage="ingest")
            with _Db(_server([{"updated_at": _iso(3)}], ts_col="updated_at")):
                pf._oldest("tasks", {"state": "eq.RUNNING"}, "updated_at", stage="draft")
                self.assertEqual(pf._SENTINELS.get("draft", 0), 0)

    def test_state_is_cleared_between_snapshots(self):
        pf._SENTINELS["ingest"] = 46
        pf._UNMEASURABLE_WHY["ingest"] = "stale"
        pf._reset_probe_state()
        self.assertEqual(pf._SENTINELS, {})
        self.assertEqual(pf._UNMEASURABLE_WHY, {})


class TestUnmeasurableIsAlwaysUnhealthy(unittest.TestCase):

    def _snapshot_with(self, rows_by_stage):
        """Fake relay keyed by the stage predicate. The timestamp column is taken from the
        fixture rows, not from the `select` clause — `_count` asks for `id` and would
        otherwise be routed to the wrong column and silently return zero."""
        def select(table, params):
            state = str(params.get("state") or params.get("status") or "")
            rows = rows_by_stage.get(state, [])
            ts_col = "created_at" if (rows and "created_at" in rows[0]) else "updated_at"
            return _server(rows, ts_col).select(table, params)
        return types.SimpleNamespace(select=select)

    def test_an_all_sentinel_stage_renders_unhealthy_not_ok(self):
        stub = self._snapshot_with({"eq.QUEUED": [{"created_at": SENTINEL}] * 30})
        with _Db(stub):
            snap = pf.snapshot()
        ingest = next(s for s in snap["stages"] if s["stage"] == "ingest")
        self.assertEqual(ingest["oldest_h"], pf.UNMEASURABLE)
        self.assertFalse(ingest["healthy"])
        self.assertFalse(snap["healthy"])

    def test_the_note_says_which_kind_of_blindness_it_is(self):
        stub = self._snapshot_with({"eq.QUEUED": [{"created_at": SENTINEL}] * 30})
        with _Db(stub):
            snap = pf.snapshot()
        ingest = next(s for s in snap["stages"] if s["stage"] == "ingest")
        self.assertIn("pinned", ingest["note"])
        self.assertNotIn("probe failed", ingest["note"])

    def test_a_failed_probe_still_reads_as_blind(self):
        def boom(table, params):
            raise RuntimeError("relay down")
        with _Db(types.SimpleNamespace(select=boom)):
            pf._sleep_patch = None
            real_sleep = pf.time.sleep
            pf.time.sleep = lambda *_: None
            try:
                age = pf._oldest("tasks", {"state": "eq.QUEUED"}, "created_at", stage="ingest")
            finally:
                pf.time.sleep = real_sleep
        self.assertEqual(age, pf.UNMEASURABLE)
        self.assertIn("BLIND", pf._UNMEASURABLE_WHY["ingest"])


class TestTheSentinelCountProbeCannotFailOpen(unittest.TestCase):
    """`_count` reports probe failure as -1. Folding that into 0 made a failed count read as
    "no sentinels", so a stage holding nothing but pinned rows rendered as an empty healthy
    dash — the same fail-open shape this module exists to prevent, one layer down."""

    def _server_that_answers_the_window_but_not_the_count(self, rows):
        def select(table, params):
            if str(params.get("select")) == "id":       # this is the _count fallback probe
                raise RuntimeError("count probe unavailable")
            return _server(rows).select(table, params)
        return types.SimpleNamespace(select=select)

    def test_all_sentinel_plus_failed_count_is_unmeasurable_not_empty(self):
        rows = [{"created_at": SENTINEL}] * 30
        with _Db(self._server_that_answers_the_window_but_not_the_count(rows)):
            age = pf._oldest("tasks", {"state": "eq.QUEUED"}, "created_at", stage="ingest")
        self.assertEqual(age, pf.UNMEASURABLE)
        self.assertIn("cannot distinguish", pf._UNMEASURABLE_WHY["ingest"])

    def test_a_genuinely_empty_stage_with_a_failed_count_is_also_not_called_empty(self):
        # Refusing to guess is the point. Both cases look identical from here, and the safe
        # reading of "I cannot tell" is not "healthy".
        with _Db(self._server_that_answers_the_window_but_not_the_count([])):
            age = pf._oldest("tasks", {"state": "eq.DONE"}, "updated_at", stage="card")
        self.assertEqual(age, pf.UNMEASURABLE)

    def test_it_renders_unhealthy_in_the_snapshot(self):
        rows = [{"created_at": SENTINEL}] * 30

        def select(table, params):
            if str(params.get("select")) == "id":
                raise RuntimeError("count probe unavailable")
            if params.get("state") == "eq.QUEUED":
                return _server(rows).select(table, params)
            return []
        with _Db(types.SimpleNamespace(select=select)):
            snap = pf.snapshot()
        ingest = next(s for s in snap["stages"] if s["stage"] == "ingest")
        self.assertFalse(ingest["healthy"])
        self.assertFalse(snap["healthy"])


if __name__ == "__main__":
    unittest.main()
