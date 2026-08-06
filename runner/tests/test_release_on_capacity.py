#!/usr/bin/env python3
"""Releases run on capacity, never on a clock (operator directive 2026-08-06).

What was actually holding releases, measured 2026-08-06:

  * `_release_due()` measured hours since the last successful/pending release, and
    RELEASE_INTERVAL_HOURS was floored at `max(6.0, ...)` — so ORCH_RELEASE_INTERVAL_HOURS
    could never lower it. A knob that looked adjustable and was not.
  * Worse, `_release_project()` returned on `int(ahead) < MIN_BATCH` BEFORE `_release_due`
    was ever called. The comment there claimed "cadence expiry flushes whatever is ready" —
    it could not, because the cadence check was unreachable for any project under the batch
    size. A project with 3 finished changes waited for 7 more, forever.

Capacity now means: nothing pending/building for that project, and a short debounce settled.
"""
import datetime
import unittest
from unittest.mock import patch

import release_train as rt


def _iso(seconds_ago):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=seconds_ago)).isoformat()


def _rel(status="success", seconds_ago=3600):
    return {"created_at": _iso(seconds_ago), "project": "p", "deploy_status": status}


class TestReleaseDecision(unittest.TestCase):

    def test_nothing_staged_is_up_to_date(self):
        self.assertEqual(rt._release_decision(0, True), "up-to-date")

    def test_capacity_free_ships_a_partial_batch(self):
        """The headline change: 3 changes ship rather than waiting for MIN_BATCH."""
        self.assertEqual(rt._release_decision(3, True, minimum=10), "release")

    def test_single_change_ships_when_capacity_is_free(self):
        self.assertEqual(rt._release_decision(1, True, minimum=10), "release")

    def test_no_capacity_holds_even_a_full_batch(self):
        """One release in flight per project, always — volume never overrides that."""
        self.assertEqual(rt._release_decision(50, False, minimum=10), "hold")


class TestReleaseDueIsCapacityBased(unittest.TestCase):

    def setUp(self):
        # Keep the real module defaults out of the assertions.
        p = patch.object(rt, "RELEASE_INTERVAL_HOURS", 6.0)
        p.start()
        self.addCleanup(p.stop)
        d = patch.object(rt, "RELEASE_DEBOUNCE_S", 60.0)
        d.start()
        self.addCleanup(d.stop)
        m = patch.object(rt, "MIN_BATCH", 10)
        m.start()
        self.addCleanup(m.stop)

    def _due(self, rows, ahead=1):
        with patch.object(rt, "_recent_releases", return_value=rows):
            return rt._release_due("p", ahead=ahead)

    def test_no_prior_release_is_due(self):
        due, why = self._due([])
        self.assertTrue(due, why)

    def test_pending_release_blocks(self):
        due, why = self._due([_rel("pending", 10)])
        self.assertFalse(due)
        self.assertIn("already in flight", why)

    def test_building_release_blocks(self):
        due, why = self._due([_rel("building", 10)])
        self.assertFalse(due)
        self.assertIn("already in flight", why)

    def test_old_success_no_longer_blocks(self):
        """THE regression this fixes: 5h since the last release used to mean 'held'."""
        due, why = self._due([_rel("success", 5 * 3600)])
        self.assertTrue(due, why)
        self.assertIn("capacity free", why)

    def test_failed_release_does_not_count_as_in_flight(self):
        due, why = self._due([_rel("failed", 600)])
        self.assertTrue(due, why)

    def test_debounce_coalesces_a_burst(self):
        """A trickle right after a release waits briefly so merges group into one release."""
        due, why = self._due([_rel("success", 5)], ahead=1)
        self.assertFalse(due)
        self.assertIn("debouncing", why)

    def test_full_batch_skips_the_debounce(self):
        """The debounce groups trickles; it must not delay real volume."""
        due, why = self._due([_rel("success", 5)], ahead=50)
        self.assertTrue(due, why)

    def test_debounce_elapsed_releases(self):
        due, why = self._due([_rel("success", 120)], ahead=1)
        self.assertTrue(due, why)

    def test_zero_debounce_disables_the_wait(self):
        with patch.object(rt, "RELEASE_DEBOUNCE_S", 0):
            due, why = self._due([_rel("success", 1)], ahead=1)
        self.assertTrue(due, why)

    def test_unreadable_timestamp_does_not_block_forever(self):
        due, why = self._due([{"created_at": "not-a-date", "deploy_status": "success"}])
        self.assertTrue(due, why)

    def test_db_failure_is_fail_soft(self):
        with patch.object(rt.db, "select", side_effect=RuntimeError("db down")):
            due, why = rt._release_due("p", ahead=1)
        self.assertTrue(due, why)

    def test_blocker_flush_lane_still_short_circuits(self):
        """NOT dead code: autopilot assigns rt.RELEASE_INTERVAL_HOURS = 0 on the module,
        bypassing the max(6.0, ...) clamp. Deleting that branch would break the hot lane."""
        with patch.object(rt, "RELEASE_INTERVAL_HOURS", 0):
            due, why = rt._release_due("p", ahead=1)
        self.assertTrue(due)
        self.assertIn("blocker-flush", why)


class TestReleaseRateIsObservable(unittest.TestCase):
    """The batching existed to avoid per-commit Vercel churn. Removing it is only safe if the
    churn stays measurable, so the rate is computed and surfaced in every decision note."""

    def test_counts_only_the_window(self):
        rows = [_rel("success", 60), _rel("success", 120),
                _rel("success", 10 * 3600)]  # outside a 6h window
        self.assertEqual(rt._release_rate_per_hour(rows, window_h=6.0), round(2 / 6.0, 3))

    def test_empty_is_zero(self):
        self.assertEqual(rt._release_rate_per_hour([]), 0.0)

    def test_bad_timestamps_are_skipped_not_fatal(self):
        rows = [{"created_at": "garbage"}, _rel("success", 60)]
        self.assertEqual(rt._release_rate_per_hour(rows, window_h=6.0), round(1 / 6.0, 3))

    def test_rate_appears_in_the_decision_note(self):
        with patch.object(rt, "_recent_releases", return_value=[_rel("success", 5 * 3600)]):
            _, why = rt._release_due("p", ahead=1)
        self.assertIn("rate=", why)


class TestMinBatchNoLongerStrands(unittest.TestCase):
    """Regression guard on the early return that made the cadence check unreachable."""

    def test_source_no_longer_returns_below_batch_size_before_checking_capacity(self):
        import inspect
        src = inspect.getsource(rt._run_for_unlocked)
        self.assertNotIn('"note": "below batch size"', src,
                         "the MIN_BATCH early return is back; capacity check is unreachable "
                         "again for any project under the batch size")

    def test_capacity_check_precedes_the_release_decision(self):
        import inspect
        src = inspect.getsource(rt._run_for_unlocked)
        self.assertLess(src.index("_release_due("), src.index("_release_decision("),
                        "_release_decision must consume the capacity verdict")

    def test_up_to_date_does_not_fall_through_to_a_release(self):
        """Testing for == 'hold' would cut an empty release when ahead == 0."""
        import inspect
        src = inspect.getsource(rt._run_for_unlocked)
        self.assertIn('decision != "release"', src,
                      "only an explicit 'release' may proceed; 'up-to-date' must stop")


if __name__ == "__main__":
    unittest.main()
