#!/usr/bin/env python3
"""A producer whose output the fleet never consumes must be rationed too.

THE GAP
-------
`producer_admission` throttled on ONE signal: what share of a producer's output turned
out to be work the fleet already had (SUPERSEDED, "duplicate", "already integrated").
That signal can only see duplicates the fleet has RESOLVED as duplicates. A task that
sits QUEUED forever is neither merged nor marked redundant, so it is invisible to it.

Measured 2026-09-09:

    producer                filed(14d)  merged  redundant  still QUEUED
    slug:chatgpt-local          1,518        2      21.5%           799

21.5% is under the 35% ceiling, so the gate never fired — while that one producer grew
to hold 888 of the 1,566 tasks in the queue, 56.7% of the entire backlog. The next
largest identified producer held 8.3%. The queue was more than half one producer's
unconsumed output and nothing in the fleet objected.

WHY SHARE AND NOT MERGE RATE
----------------------------
The module docstring rejects a merge-rate gate and is right to: when the fleet's own
merge machinery stalls, merge rate collapses for everyone, so it condemns producers for
a fault that is not theirs — it would have throttled `backlog-batch`, which merged
nothing but filed only 2.4% redundant work.

Queue share does not have that defect because it is RELATIVE. A fleet-wide stall lifts
every producer's backlog together and leaves their shares roughly where they were. That
property is the whole justification for the signal, so it is pinned here
(`test_a_fleet_wide_stall_does_not_throttle_a_minority_producer`) rather than left as a
claim in a comment.
"""
import os
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import producer_admission as pa  # noqa: E402


class FakeDB:
    """Enough of the db.select surface to drive _measure and _fleet_queued.

    The producer's own QUEUED count is NOT served here — `_measure` derives it from the
    window rows it already fetched, so `_rows(...)` controls it via how many rows carry
    state QUEUED. Only the fleet total costs a query.
    """

    def __init__(self, filed_rows, my_queued, total_queued):
        self.filed_rows = filed_rows
        self.my_queued = my_queued
        self.total_queued = total_queued
        self.calls = 0

    def select(self, _table, query):
        self.calls += 1
        if query.get("state") == "eq.QUEUED":
            return [{"id": i} for i in range(self.total_queued)]
        return self.filed_rows


def _rows(filed, redundant=0, merged=0, recent=0):
    """`filed` task rows, of which `redundant` look duplicate and `recent` are <24h."""
    import time

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5 * 86400))
    out = []
    for i in range(filed):
        row = {"slug": f"chatgpt-local-reconcile-x{i}", "state": "QUEUED", "note": "",
               "created_at": now if i < recent else old}
        if i < redundant:
            row["state"] = "SUPERSEDED"
        elif i < redundant + merged:
            row["state"] = "MERGED"
        out.append(row)
    return out


class QueueShareThrottleTests(unittest.TestCase):
    def setUp(self):
        pa.reset_cache()
        self.addCleanup(pa.reset_cache)
        for var in ("ORCH_PRODUCER_QUEUE_SHARE_CEILING", "ORCH_PRODUCER_QUEUE_MIN_TOTAL",
                    "ORCH_PRODUCER_REDUNDANT_CEILING", "ORCH_PRODUCER_MIN_SAMPLE"):
            os.environ.pop(var, None)
        self.row = {"slug": "chatgpt-local-reconcile-tomorrow-abc123"}

    def test_the_measured_offender_is_now_throttled(self):
        """1,518 filed / 21.5% redundant / 888 of 1,566 queued — the real numbers."""
        db = FakeDB(_rows(1518, redundant=326, merged=2, recent=200),
                    my_queued=888, total_queued=1566)
        admit, reason = pa.verdict(self.row, db=db)

        self.assertFalse(admit, "56.7% of the queue from one producer must ration it")
        self.assertIn("QUEUED", reason)
        self.assertIn("share ceiling", reason)

    def test_volume_alone_never_throttles_a_clean_producer(self):
        """The principle the first version of this change broke.

        A single healthy producer that is the only one filing will hold most of the
        queue. Throttling it for that is the merge-rate mistake in a new costume:
        condemning a producer for the fleet's state rather than its own conduct.
        """
        db = FakeDB(_rows(1518, redundant=15, merged=0, recent=400),
                    my_queued=1400, total_queued=1566)   # 89% of the queue, 1% redundant
        admit, reason = pa.verdict(self.row, db=db)
        self.assertTrue(admit,
                        f"a 1%-redundant producer must be admitted at any share: {reason}")

    def test_the_same_producer_was_admitted_before_this_signal(self):
        """Proves the gap was real: redundancy alone still says admit."""
        db = FakeDB(_rows(1518, redundant=326, merged=2, recent=200),
                    my_queued=888, total_queued=1566)
        os.environ["ORCH_PRODUCER_QUEUE_SHARE_CEILING"] = "1.0"   # disable the new gate
        try:
            admit, _ = pa.verdict(self.row, db=db)
        finally:
            os.environ.pop("ORCH_PRODUCER_QUEUE_SHARE_CEILING", None)
        self.assertTrue(admit,
                        "21.5% redundancy is under the 35% ceiling — the old gate could "
                        "not see this producer, which is why the signal was added")

    def test_a_fleet_wide_stall_does_not_throttle_a_minority_producer(self):
        """The defect that disqualified merge rate must not reappear here.

        A huge, entirely stalled queue in which this producer holds only 8.3% — the
        measured share of the well-behaved `backlog-batch` producer — must admit.
        """
        db = FakeDB(_rows(400, redundant=10, merged=0, recent=5),
                    my_queued=130, total_queued=1566)
        admit, reason = pa.verdict(self.row, db=db)
        self.assertTrue(admit, f"a minority share must not be throttled: {reason}")

    def test_a_tiny_queue_is_not_a_share_signal(self):
        """2 of 3 is 67% and means nothing."""
        db = FakeDB(_rows(100, redundant=2, recent=50), my_queued=2, total_queued=3)
        self.assertTrue(pa.verdict(self.row, db=db)[0])

    def test_share_gate_still_respects_the_daily_quota_floor(self):
        """Throttling is rationing, not a ban: under quota it still admits."""
        db = FakeDB(_rows(1518, redundant=326, merged=2, recent=1),
                    my_queued=888, total_queued=1566)
        admit, _ = pa.verdict(self.row, db=db)
        self.assertTrue(admit, "1 filed in 24h is under any quota")

    def test_redundancy_throttle_still_fires_on_its_own(self):
        """The original signal must be untouched by the addition."""
        db = FakeDB(_rows(600, redundant=400, recent=200), my_queued=5, total_queued=1566)
        admit, reason = pa.verdict(self.row, db=db)
        self.assertFalse(admit)
        self.assertIn("work the fleet already had", reason)

    def test_below_min_sample_still_admits(self):
        db = FakeDB(_rows(10, redundant=10, recent=10), my_queued=900, total_queued=1000)
        self.assertTrue(pa.verdict(self.row, db=db)[0])

    def test_unattributable_rows_are_always_admitted(self):
        self.assertTrue(pa.verdict({"slug": "x"}, db=FakeDB([], 0, 0))[0])

    def test_an_unmeasurable_queue_does_not_throttle(self):
        """Fails open, like every other read in this module."""
        class Broken(FakeDB):
            def select(self, table, query):
                if query.get("state") == "eq.QUEUED":
                    raise RuntimeError("PostgREST down")
                return self.filed_rows

        db = Broken(_rows(600, redundant=10, recent=200), 0, 0)
        self.assertTrue(pa.verdict(self.row, db=db)[0],
                        "an unreadable queue must not become a verdict about a producer")

    def test_queue_share_is_reported_in_the_stats(self):
        # 100 filed, 5 of them SUPERSEDED, so 95 are still QUEUED.
        db = FakeDB(_rows(100, redundant=5), my_queued=95, total_queued=1000)
        stats = pa._measure("slug:chatgpt-local", db)
        self.assertEqual(stats["queued"], 95)
        self.assertEqual(stats["queue_total"], 1000)
        self.assertAlmostEqual(stats["queue_share"], 0.095)

    def test_measuring_costs_exactly_one_extra_read(self):
        """The insert path stays cheap: the window scan plus one fleet-total query."""
        db = FakeDB(_rows(100, redundant=5), my_queued=95, total_queued=1000)
        pa._measure("slug:chatgpt-local", db)
        self.assertEqual(db.calls, 2)

    def test_ceiling_is_configurable(self):
        # 20% redundant: under the 35% ceiling, over the 17.5% tightened one.
        db = FakeDB(_rows(600, redundant=120, recent=200),
                    my_queued=500, total_queued=1566)   # 31.9% share
        self.assertTrue(pa.verdict(self.row, db=db)[0],
                        "31.9% is under the default 40% share ceiling")
        pa.reset_cache()
        os.environ["ORCH_PRODUCER_QUEUE_SHARE_CEILING"] = "0.25"
        try:
            self.assertFalse(pa.verdict(self.row, db=db)[0],
                             "lowering the share ceiling must tighten the redundancy "
                             "ceiling and catch this producer")
        finally:
            os.environ.pop("ORCH_PRODUCER_QUEUE_SHARE_CEILING", None)

    def test_quota_uses_the_tightened_ceiling(self):
        """Throttled at 17.5% then handed the 35% quota would undo the throttle."""
        self.assertLess(pa.quota_for(0.30, ceiling=0.175), pa.quota_for(0.30))


if __name__ == "__main__":
    unittest.main()
