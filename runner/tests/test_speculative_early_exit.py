"""Early exit in the speculative executor: stop paying for work already won.

runner/speculative_executor.execute_speculative() is the value-aware routing
path — it runs candidates in parallel, cancels lower-priority work once a
higher-priority result lands, and stops entirely once max_results successes are
in. That whole mechanism had NO direct test coverage: the only suite importing
the module (test_hivemind_v15.py) never calls execute_speculative and never
touches early_exits.

Untested early-exit logic is the expensive kind to get wrong in both directions
— exiting too early loses results the caller was promised, exiting too late
keeps paying for candidates whose answer is already known — so both directions
are asserted here.

Deliberately dependency-free: plain callables and threads, no provider, no DB,
no network. The suite's hermetic guard blocks sockets anyway.
"""
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import speculative_executor as se


def _ok(value, delay=0.0):
    def _fn():
        if delay:
            time.sleep(delay)
        return value
    return _fn


def _boom():
    raise RuntimeError("candidate failed")


def _candidate(task_id, fn, priority=0):
    return se.TaskCandidate(task_id, fn, priority=priority)


class TestExecuteSpeculativeBasics(unittest.TestCase):
    def test_no_candidates_returns_empty(self):
        self.assertEqual(se.execute_speculative([]), [])

    def test_all_candidates_run_when_nothing_limits_them(self):
        cands = [_candidate(f"t{i}", _ok(i)) for i in range(4)]
        results = se.execute_speculative(cands, cancel_on_priority=False)
        self.assertEqual(len(results), 4)
        self.assertTrue(all(r.ok for r in results))
        self.assertEqual({r.value for r in results}, {0, 1, 2, 3})

    def test_a_failing_candidate_does_not_abort_the_batch(self):
        cands = [_candidate("bad", _boom), _candidate("good", _ok("v"))]
        results = se.execute_speculative(cands, cancel_on_priority=False)
        self.assertEqual(len(results), 2)
        self.assertEqual({r.task_id for r in results if r.ok}, {"good"})
        bad = next(r for r in results if r.task_id == "bad")
        self.assertFalse(bad.ok)
        self.assertIsNotNone(bad.error)

    def test_disabled_executor_returns_empty_without_running_anything(self):
        ran = []
        cands = [_candidate("t", lambda: ran.append(1))]
        with patch.object(se, "ENABLED", False):
            self.assertEqual(se.execute_speculative(cands), [])
        self.assertEqual(ran, [], "a disabled executor must not execute work")


class TestEarlyExit(unittest.TestCase):
    def test_max_results_stops_collecting_once_satisfied(self):
        before = se.get_stats().get("early_exits", 0)
        # Staggered so the last candidates cannot finish before the exit fires.
        cands = [_candidate(f"t{i}", _ok(i, delay=0.05 * i)) for i in range(6)]
        results = se.execute_speculative(cands, cancel_on_priority=False, max_results=2)
        self.assertGreaterEqual(sum(1 for r in results if r.ok), 2)
        # The saving is the whole point: we must NOT have awaited all six.
        self.assertLess(len(results), 6,
                        "early exit did not stop collection; every candidate was awaited")
        # And it is recorded, so the saving is observable to operators.
        self.assertGreater(se.get_stats().get("early_exits", 0), before)

    def test_early_exit_does_not_fire_when_max_results_is_unreachable(self):
        # Exiting too LATE is a cost bug; exiting when it should not is a
        # correctness bug that silently drops promised results.
        before = se.get_stats().get("early_exits", 0)
        cands = [_candidate(f"t{i}", _ok(i)) for i in range(3)]
        results = se.execute_speculative(cands, cancel_on_priority=False, max_results=99)
        self.assertEqual(len(results), 3)
        self.assertEqual(se.get_stats().get("early_exits", 0), before)

    def test_no_max_results_means_every_candidate_is_collected(self):
        before = se.get_stats().get("early_exits", 0)
        cands = [_candidate(f"t{i}", _ok(i)) for i in range(3)]
        results = se.execute_speculative(cands, cancel_on_priority=False)
        self.assertEqual(len(results), 3)
        self.assertEqual(se.get_stats().get("early_exits", 0), before)

    def test_failures_do_not_count_toward_max_results(self):
        # Otherwise a batch of failures would "satisfy" the caller and exit with
        # nothing usable — the worst possible early exit.
        cands = [_candidate("b1", _boom), _candidate("b2", _boom),
                 _candidate("good", _ok("v", delay=0.05))]
        results = se.execute_speculative(cands, cancel_on_priority=False, max_results=1)
        self.assertEqual([r.task_id for r in results if r.ok], ["good"])


class TestStatsContract(unittest.TestCase):
    def test_stats_expose_the_counters_callers_read(self):
        stats = se.get_stats()
        for key in ("completed", "cancelled", "errors", "early_exits"):
            self.assertIn(key, stats)
            self.assertIsInstance(stats[key], int)

    def test_get_stats_returns_a_copy_not_the_live_dict(self):
        # A caller mutating the snapshot must not corrupt the counters.
        snapshot = se.get_stats()
        snapshot["completed"] = -12345
        self.assertNotEqual(se.get_stats().get("completed"), -12345)


if __name__ == "__main__":
    unittest.main()
