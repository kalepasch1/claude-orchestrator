"""_rate_unscored is a queue DRAIN, so it must not be able to starve its own tail.

Every row it selects is written back with a quality_score, so a row it never selects is
never scored by anything. Ordered created_at.desc with a limit, the batch always refilled
from the front and the far end was unreachable by construction. Measured on the live table
before the fix: 874,805 unscored operations against 99,986 scored, 861,838 of them older
than a week, the oldest 52 days, while the job took the newest 40 per run.

The database layer had been logging TRUNCATED SCAN against that exact line for weeks, and
its wording named the consequence: "if the caller acts on work, the far end of the queue
is being starved."
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_triage_review as atr  # noqa: E402


class FakeDB(object):
    def __init__(self, rows=None, fail_ids=()):
        self.rows = list(rows or [])
        self.fail_ids = set(fail_ids)
        self.calls = []
        self.updated = []

    def select(self, table, params=None):
        params = params or {}
        self.calls.append((table, params))
        if table != "app_operations":
            return []
        rows = [r for r in self.rows if r.get("quality_score") is None]
        order = params.get("order") or ""
        if order.startswith("created_at."):
            rows.sort(key=lambda r: r["created_at"],
                      reverse=order.endswith(".desc"))
        limit = int(params.get("limit") or 10**9)
        return rows[:limit]

    def update(self, table, where, patch):
        if where.get("id") in self.fail_ids:
            raise RuntimeError(f"row {where['id']} cannot be written")
        self.updated.append(where["id"])
        for r in self.rows:
            if r["id"] == where["id"]:
                r.update(patch)


def ops(n, start=0):
    """n unscored operations, id/created_at ascending so 'oldest' is unambiguous."""
    return [{"id": i, "created_at": f"2026-07-{(i % 28) + 1:02d}T00:00:{i % 60:02d}",
             "app": "a", "operation": "op", "task_class": "plan", "provider": "local",
             "model": "m", "cost_usd": 0.0, "latency_ms": 10, "ok": True,
             "quality_score": None}
            for i in range(start, start + n)]


class DrainIsFifo(unittest.TestCase):
    def setUp(self):
        self.real_db = atr.db
        self.fake = FakeDB(rows=ops(200))
        # Deterministic ordering by created_at requires unique timestamps.
        for i, r in enumerate(self.fake.rows):
            r["created_at"] = f"2026-07-01T00:00:{i:04d}"
        atr.db = self.fake
        os.environ.pop("ORCH_APP_REVIEW_USE_MODEL", None)

    def tearDown(self):
        atr.db = self.real_db

    def test_the_query_asks_for_oldest_first(self):
        atr._rate_unscored()
        sel = [p for t, p in self.fake.calls
               if t == "app_operations" and p.get("limit") == str(atr.SAMPLE)]
        self.assertTrue(sel, "expected the batch select")
        self.assertEqual(sel[0].get("order"), "created_at.asc",
                         "newest-first makes the tail of the queue unreachable")

    def test_the_oldest_rows_are_the_ones_scored(self):
        atr._rate_unscored()
        self.assertEqual(sorted(self.fake.updated), list(range(atr.SAMPLE)),
                         "a drain must take from the front of the queue")

    def test_repeated_runs_reach_the_far_end(self):
        """The property that failed before: run enough times and everything is scored."""
        for _ in range(200 // atr.SAMPLE + 2):
            atr._rate_unscored()
        remaining = [r for r in self.fake.rows if r.get("quality_score") is None]
        self.assertEqual(remaining, [],
                         "with newest-first ordering these rows could never be reached")

    def test_newly_arrived_rows_do_not_displace_the_backlog(self):
        atr._rate_unscored()
        # A burst of new operations arrives after the first pass.
        newer = ops(100, start=1000)
        for i, r in enumerate(newer):
            r["created_at"] = f"2026-09-01T00:00:{i:04d}"
        self.fake.rows.extend(newer)

        before = {r["id"] for r in self.fake.rows
                  if r.get("quality_score") is None and r["id"] < 1000}
        atr._rate_unscored()
        after = {r["id"] for r in self.fake.rows
                 if r.get("quality_score") is None and r["id"] < 1000}
        self.assertLess(len(after), len(before),
                        "new arrivals must not push the existing backlog further out of reach")


class PoisonRowsAreVisible(unittest.TestCase):
    """FIFO introduces head-of-line blocking, so a failing row cannot be silent."""

    def setUp(self):
        self.real_db = atr.db
        rows = ops(5)
        for i, r in enumerate(rows):
            r["created_at"] = f"2026-07-01T00:00:{i:04d}"
        self.fake = FakeDB(rows=rows, fail_ids={0})
        atr.db = self.fake
        os.environ.pop("ORCH_APP_REVIEW_USE_MODEL", None)

    def tearDown(self):
        atr.db = self.real_db

    def test_a_failing_row_does_not_stop_the_rest_of_the_batch(self):
        scored = atr._rate_unscored()
        self.assertEqual(scored, 4, "one bad row must not abort the batch")

    def test_a_failing_row_is_reported(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            atr._rate_unscored()
        out = buf.getvalue()
        self.assertIn("could not be scored", out)
        self.assertIn("FRONT of the next run", out,
                      "the head-of-line consequence is the point of the message")


class BacklogIsReported(unittest.TestCase):
    def setUp(self):
        self.real_db = atr.db

    def tearDown(self):
        atr.db = self.real_db

    def test_a_shallow_backlog_reports_an_exact_count(self):
        atr.db = FakeDB(rows=ops(7))
        b = atr._unscored_backlog()
        self.assertEqual(b["remaining"], 7)
        self.assertFalse(b["at_least"])

    def test_a_deep_backlog_is_reported_as_a_lower_bound(self):
        atr.db = FakeDB(rows=ops(atr.BACKLOG_PROBE + 50))
        b = atr._unscored_backlog()
        self.assertEqual(b["remaining"], atr.BACKLOG_PROBE)
        self.assertTrue(b["at_least"],
                        "an exact count over ~875k rows every 30 minutes is not worth paying for")

    def test_a_broken_probe_does_not_break_the_job(self):
        class Broken(FakeDB):
            def select(self, *a, **k):
                raise RuntimeError("db down")

        atr.db = Broken()
        b = atr._unscored_backlog()
        self.assertIsNone(b["remaining"])


if __name__ == "__main__":
    unittest.main()
