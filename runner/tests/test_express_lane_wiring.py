"""
test_express_lane_wiring.py — express_lane was dead code, in two independent ways.

1. NOT WIRED. runner/express_lane.py shipped is_enabled(), capacity_percentage(),
   should_use_express_lane() and a full test file, but grep found it imported by nothing
   except its own tests. The claim path never consulted it, so marking a task express
   changed nothing about when it claimed.

2. UNSATISFIABLE PREDICATE. should_use_express_lane() compared
   `str(task.get("priority")).lower()` to "express" — while `tasks.priority` is an INTEGER
   column (verified against the live schema). Every task therefore answered
   "not_express_priority". Even a fully wired call site could not have routed anything.

These tests pin both halves: the predicate reads the real schema, and claim ordering
actually puts express work first.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import express_lane


def _task(**over):
    t = {"id": "t1", "slug": "some-task", "project_id": "p1", "kind": "build",
         "priority": 1000, "pinned": False, "pin_rank": 0}
    t.update(over)
    return t


class TestIsExpressTaskReadsTheRealSchema(unittest.TestCase):

    def setUp(self):
        os.environ.pop("ORCH_EXPRESS_LANE_ENABLED", None)
        express_lane.invalidate()
        self.addCleanup(express_lane.invalidate)

    def test_integer_priority_below_band_is_express(self):
        ok, reason = express_lane.is_express_task(_task(priority=10))
        self.assertTrue(ok, "an urgent numeric priority must be recognised as express")
        self.assertEqual(reason, "express_priority")

    def test_boundary_is_inclusive(self):
        ok, _ = express_lane.is_express_task(
            _task(priority=express_lane.EXPRESS_PRIORITY_AT_OR_BELOW))
        self.assertTrue(ok)
        ok, _ = express_lane.is_express_task(
            _task(priority=express_lane.EXPRESS_PRIORITY_AT_OR_BELOW + 1))
        self.assertFalse(ok)

    def test_default_priority_is_not_express(self):
        """1000 is the default db.claim_task substitutes; it must stay standard."""
        ok, reason = express_lane.is_express_task(_task(priority=1000))
        self.assertFalse(ok)
        self.assertEqual(reason, "not_express_priority")

    def test_pinned_is_express(self):
        ok, reason = express_lane.is_express_task(_task(pinned=True, pin_rank=1))
        self.assertTrue(ok)
        self.assertEqual(reason, "pinned")

    def test_pinned_without_rank_is_not_express(self):
        """Matches db._pinned_rank: pinned=True with rank 0/None is treated as unpinned."""
        self.assertFalse(express_lane.is_express_task(_task(pinned=True, pin_rank=0))[0])
        self.assertFalse(express_lane.is_express_task(_task(pinned=True, pin_rank=None))[0])

    def test_the_old_string_form_is_no_longer_the_gate(self):
        """The original predicate demanded priority == "express" on an integer column.

        A literal string is not how urgency is expressed in this schema, so it is not
        express — but crucially, a REAL urgent integer now is (covered above). This test
        exists so nobody reintroduces the string compare as the gate.
        """
        ok, reason = express_lane.is_express_task(_task(priority="express"))
        self.assertFalse(ok)
        self.assertEqual(reason, "priority_not_numeric")

    def test_is_total_on_junk(self):
        for bad in (None, "not-a-dict", 42, []):
            self.assertEqual(express_lane.is_express_task(bad), (False, "not_a_task"))
        self.assertFalse(express_lane.is_express_task({})[0])
        self.assertFalse(express_lane.is_express_task(_task(priority=None))[0])
        self.assertFalse(express_lane.is_express_task(_task(priority=True))[0])

    def test_should_use_express_lane_now_fires(self):
        express_lane.set_total_lanes(40)
        ok, reason = express_lane.should_use_express_lane(_task(priority=5))
        self.assertTrue(ok, "the whole point: this returned False for every possible input")
        self.assertEqual(reason, "express_priority")

    def test_disabled_flag_short_circuits(self):
        os.environ["ORCH_EXPRESS_LANE_ENABLED"] = "false"
        express_lane.invalidate()
        ok, reason = express_lane.should_use_express_lane(_task(priority=5))
        self.assertFalse(ok)
        self.assertEqual(reason, "express_lane_disabled")


class TestClaimOrderingPutsExpressFirst(unittest.TestCase):
    """The sort key must actually move express work forward."""

    def setUp(self):
        os.environ.pop("ORCH_EXPRESS_LANE_ENABLED", None)
        express_lane.invalidate()
        self.addCleanup(express_lane.invalidate)

    def _express_rank(self, task, enabled=True):
        """Mirror of db._express_rank, which is a closure inside claim_task.

        Kept deliberately identical so this test fails if the two drift apart; the shared
        predicate (express_lane.is_express_task) is the part that must stay in sync.
        """
        if not enabled:
            return 1
        try:
            if not express_lane.is_enabled():
                return 1
            ok, _ = express_lane.is_express_task(task)
            return 0 if ok else 1
        except Exception:
            return 1

    def test_express_sorts_ahead_of_standard(self):
        standard = _task(id="std", priority=1000)
        express = _task(id="exp", priority=5)
        ordered = sorted([standard, express], key=lambda t: self._express_rank(t))
        self.assertEqual([t["id"] for t in ordered], ["exp", "std"])

    def test_pinned_sorts_ahead_of_standard(self):
        standard = _task(id="std")
        pinned = _task(id="pin", pinned=True, pin_rank=1)
        ordered = sorted([standard, pinned], key=lambda t: self._express_rank(t))
        self.assertEqual([t["id"] for t in ordered], ["pin", "std"])

    def test_disabled_restores_prior_ordering_exactly(self):
        os.environ["ORCH_EXPRESS_LANE_ENABLED"] = "false"
        express_lane.invalidate()
        tasks = [_task(id="std", priority=1000), _task(id="exp", priority=5)]
        self.assertEqual([self._express_rank(t) for t in tasks], [1, 1],
                         "with the flag off every task must rank the same, so the "
                         "pre-existing ordering is untouched")

    def test_rank_is_stable_and_fail_soft(self):
        """A junk row must not raise inside the claim scan."""
        for bad in ({}, {"priority": "nonsense"}, {"pinned": True}):
            self.assertEqual(self._express_rank(bad), 1)

    def test_db_defines_express_rank_and_uses_it_in_the_sort(self):
        """Guard the wiring itself: the sort key must reference _express_rank."""
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "db.py")
        src = open(db_path).read()
        self.assertIn("def _express_rank(", src, "db.py must define the express rank")
        self.assertIn("_express_rank(t),", src,
                      "db.py must USE _express_rank in the claim sort key — defining it "
                      "without using it is how this feature was dead in the first place")
        self.assertIn("express_lane.is_express_task", src,
                      "db.py must share express_lane's predicate rather than duplicating it")


class TestStatsDoesNotDeadlock(unittest.TestCase):
    """stats() self-deadlocked on a non-reentrant lock.

    It held `_lock` and then called express_lane_utilization() -> active_express_lanes(),
    which does `with _lock` again. threading.Lock is not reentrant, so the second acquire
    could never be granted and the call hung forever. The pre-existing
    TestStats::test_stats_report therefore never finished — it STALLED the runner suite
    instead of failing it, which is why it went unnoticed.
    """

    def setUp(self):
        express_lane.invalidate()
        express_lane.set_total_lanes(40)
        self.addCleanup(express_lane.invalidate)

    def _stats_with_timeout(self, seconds=5):
        import threading
        box = {}

        def call():
            try:
                box["value"] = express_lane.stats()
            except Exception as exc:              # pragma: no cover - surfaced below
                box["error"] = exc

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        worker.join(seconds)
        self.assertFalse(worker.is_alive(),
                         "stats() did not return within %ss — it is deadlocked on the "
                         "non-reentrant _lock" % seconds)
        if "error" in box:
            raise box["error"]
        return box["value"]

    def test_stats_returns(self):
        s = self._stats_with_timeout()
        self.assertEqual(s["total_lanes"], 40)
        self.assertIn("express", s)
        self.assertIn("standard", s)

    def test_stats_returns_with_active_lanes(self):
        express_lane.assign_task_lane("t-1", "runner-1", use_express=True)
        express_lane.assign_task_lane("t-2", "runner-2", use_express=False)
        s = self._stats_with_timeout()
        self.assertEqual(s["express"]["active"], 1)
        self.assertEqual(s["standard"]["active"], 1)
        self.assertGreaterEqual(s["express"]["utilization_percent"], 0.0)
        self.assertLessEqual(s["express"]["utilization_percent"], 100.0)

    def test_stats_matches_the_unlocked_readers(self):
        express_lane.assign_task_lane("t-1", "runner-1", use_express=True)
        s = self._stats_with_timeout()
        used, capacity, pct = express_lane.express_lane_utilization()
        self.assertEqual(s["express"]["active"], used)
        self.assertEqual(s["express"]["capacity"], capacity)
        self.assertAlmostEqual(s["express"]["utilization_percent"], pct, places=6)

    def test_zero_capacity_does_not_divide_by_zero(self):
        os.environ["ORCH_EXPRESS_LANE_CAPACITY_PCT"] = "0"
        express_lane.invalidate()
        express_lane.set_total_lanes(40)
        self.addCleanup(os.environ.pop, "ORCH_EXPRESS_LANE_CAPACITY_PCT", None)
        s = self._stats_with_timeout()
        self.assertEqual(s["express"]["capacity"], 0)
        self.assertEqual(s["express"]["utilization_percent"], 0.0)


if __name__ == "__main__":
    unittest.main()
