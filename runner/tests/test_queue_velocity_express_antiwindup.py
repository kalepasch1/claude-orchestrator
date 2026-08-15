#!/usr/bin/env python3
"""Pinned express lane vs. the queue-velocity PID.

The express lane at claim time is implemented in db.claim_task (see
test_pinned_express_lane.py). What was missing is the other half: the PID controller that
drains the queue treated pinned work as ordinary backlog. Two consequences, both fixed here:

  1. _shelve_lowest_ev ordered by confidence.asc with no pinned filter, so a pinned burst
     arriving during a backlog could be shelved by the controller — the express lane's own
     work was the first thing dropped, because pinned items are new and often low-confidence.
  2. A pinned burst spiked depth -> velocity -> integral, winding the integral over the shelve
     threshold and firing the I-action against unrelated queued work.

The integral now accumulates effective (non-pinned) depth, and pinned tasks are excluded from
shelving both server-side and defensively in the loop.

Imports are flat (`import queue_velocity`), matching conftest.py and the rest of the suite.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import queue_velocity as qv


class _Harness:
    """Drive qv.run() over a scripted sequence of (total_depth, pinned_depth) samples."""

    def __init__(self, test, samples):
        self.test = test
        self.samples = list(samples)
        self.i = 0
        self.shelve_calls = []

    def _depth(self):
        return self.samples[min(self.i, len(self.samples) - 1)][0]

    def _pinned(self):
        return self.samples[min(self.i, len(self.samples) - 1)][1]

    def _shelve(self, count):
        self.shelve_calls.append(count)
        return count

    def run_all(self):
        decisions = []
        with patch.object(qv, "_queue_depth", side_effect=self._depth), \
             patch.object(qv, "_pinned_depth", side_effect=self._pinned), \
             patch.object(qv, "_shelve_lowest_ev", side_effect=self._shelve), \
             patch.object(qv, "_pause_generators"), \
             patch.object(qv, "_unpause_generators"):
            for _ in self.samples:
                decisions.append(qv.run())
                self.i += 1
        return decisions


class TestPinnedBurstDoesNotWindUpIntegral(unittest.TestCase):

    def setUp(self):
        # Isolate controller state; qv writes STATE_FILE next to CLAUDE_ORCH_HOME.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        p = patch.object(qv, "STATE_FILE", os.path.join(self._tmp.name, "state.json"))
        p.start()
        self.addCleanup(p.stop)
        g = patch.object(qv, "GENERATOR_PAUSE_FILE", os.path.join(self._tmp.name, "pause.json"))
        g.start()
        self.addCleanup(g.stop)

    def test_pinned_burst_does_not_grow_the_integral(self):
        """A burst of pinned work spikes depth but must leave the integral flat.

        Baseline queue is a steady 600 non-pinned. 2,000 pinned items land, then drain.
        Depth swings hard; the integral must not move, because none of that was backlog.
        """
        samples = [
            (600, 0),      # steady state
            (2600, 2000),  # burst of 2,000 pinned items
            (2600, 2000),  # still queued, claiming
            (1600, 1000),  # express lane draining fast
            (600, 0),      # drained
        ]
        decisions = _Harness(self, samples).run_all()

        for d in decisions:
            self.assertEqual(
                d["integral"], 0,
                f"pinned burst wound up the integral: {d}")
        # And the raw depth really did swing, i.e. the test is exercising the burst.
        self.assertEqual(max(d["depth"] for d in decisions), 2600)
        self.assertEqual(max(d["pinned_depth"] for d in decisions), 2000)

    def test_real_backlog_still_grows_the_integral(self):
        """Guard against over-correcting: non-pinned growth must still integrate."""
        samples = [(600, 0), (1100, 0), (1600, 0)]
        decisions = _Harness(self, samples).run_all()
        self.assertGreater(decisions[-1]["integral"], 0,
                           "genuine backlog no longer builds integral")
        self.assertEqual(decisions[-1]["effective_velocity"], 500)

    def test_integral_stays_bounded_under_sustained_pinned_pressure(self):
        """Integral must remain <= INTEGRAL_MAX no matter how long the burst lasts."""
        samples = [(1000 + i * 500, 500 + i * 500) for i in range(20)]
        decisions = _Harness(self, samples).run_all()
        for d in decisions:
            self.assertLessEqual(d["integral"], qv.INTEGRAL_MAX)
        self.assertEqual(decisions[-1]["integral"], 0,
                         "growth was entirely pinned; integral should stay at zero")

    def test_i_action_does_not_fire_on_a_pinned_burst_alone(self):
        """The controller must not shelve anything just because pinned work arrived."""
        big = qv.INTEGRAL_SHELVE_THRESHOLD * 4
        samples = [(500, 0)] + [(500 + big, big)] * 4
        h = _Harness(self, samples)
        decisions = h.run_all()
        self.assertFalse(any(d["i_action"] for d in decisions),
                         "I-action fired against a pure pinned burst")
        self.assertEqual(h.shelve_calls, [], "shelved work during a pinned burst")

    def test_effective_depth_never_negative(self):
        """Defensive: a stale/racing pinned count must not produce a negative depth."""
        samples = [(100, 400)]
        decisions = _Harness(self, samples).run_all()
        self.assertEqual(decisions[0]["effective_depth"], 0)

    def test_history_without_effective_depth_falls_back(self):
        """State written by the previous version has no effective_depth key."""
        qv._save_state({"history": [{"t": 0, "depth": 500}], "integral": 0,
                        "paused_at": None, "shelve_pressure": 0})
        decisions = _Harness(self, [(700, 0)]).run_all()
        # Falls back to depth for the legacy entry: 700 - 500 = 200.
        self.assertEqual(decisions[0]["effective_velocity"], 200)


class TestShelvingNeverTouchesPinnedTasks(unittest.TestCase):

    def test_query_excludes_pinned_server_side(self):
        captured = {}

        def _sel(table, params=None):
            captured.update(params or {})
            return []

        with patch.object(qv.db, "select", side_effect=_sel):
            qv._shelve_lowest_ev(10)

        self.assertEqual(captured.get("pinned"), "not.is.true",
                         "shelve query does not exclude pinned tasks")

    def test_pinned_row_is_skipped_even_if_the_filter_is_ignored(self):
        """Deployments predating the pinned migration can drop the filter silently."""
        rows = [
            {"id": "1", "slug": "pinned-express", "confidence": 0.1,
             "project_id": "p1", "pinned": True},
            {"id": "2", "slug": "ordinary", "confidence": 0.2,
             "project_id": "p1", "pinned": False},
        ]
        updated = []

        with patch.object(qv.db, "select", return_value=rows), \
             patch.object(qv.db, "update", side_effect=lambda *a, **k: updated.append(a)), \
             patch.object(qv, "_recovery_action", return_value=("shelve", "no branch")):
            shelved = qv._shelve_lowest_ev(10)

        self.assertEqual(shelved, 1, "expected exactly the one unpinned task to be shelved")
        self.assertEqual(len(updated), 1)
        self.assertIn("id", updated[0][1])
        self.assertEqual(updated[0][1]["id"], "2", "shelved the pinned express task")


class TestPinnedDepthIsFailSoft(unittest.TestCase):

    def test_count_failure_degrades_to_zero(self):
        """A pinned-count failure must not suppress the I-action; it degrades to old behaviour."""
        with patch.object(qv.db, "count", side_effect=RuntimeError("boom")):
            self.assertEqual(qv._pinned_depth(), 0)

    def test_none_result_degrades_to_zero(self):
        with patch.object(qv.db, "count", return_value=None):
            self.assertEqual(qv._pinned_depth(), 0)


if __name__ == "__main__":
    unittest.main()
