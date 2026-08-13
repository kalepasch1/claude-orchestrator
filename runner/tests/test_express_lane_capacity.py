#!/usr/bin/env python3
"""express_lane capacity was computed against a lane count that did not exist.

`_total_lanes` was a module constant of 40 that `set_total_lanes()` was meant to
update — and nothing ever called `set_total_lanes()`. The machine's real limit is
`MAX_PARALLEL` (runner.py:192, default 12). So on a stock box,
`ORCH_EXPRESS_LANE_CAPACITY_PCT=15` reserved `max(1, int(40 * 0.15))` = 6 of 12
lanes: **50% of the machine, advertised as 15%**, with `standard_lane_capacity()`
reporting a nonsense 34.

The fix reads MAX_PARALLEL live (same reason runner.py re-checks eff_limit every
dispatch loop rather than snapshotting at boot) and never lets express take the
last lane.

Run: python3 -m unittest runner.tests.test_express_lane_capacity -v
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ORCH_DB_URL", "")
os.environ.setdefault("ORCH_DB_ENABLED", "false")

import express_lane as el


class TotalLanesTest(unittest.TestCase):
    def setUp(self):
        el.invalidate()
        self.addCleanup(el.invalidate)

    def test_reads_max_parallel(self):
        with patch.dict(os.environ, {"MAX_PARALLEL": "12"}):
            self.assertEqual(el.total_lanes(), 12)

    def test_tracks_a_live_change(self):
        with patch.dict(os.environ, {"MAX_PARALLEL": "12"}):
            first = el.total_lanes()
        with patch.dict(os.environ, {"MAX_PARALLEL": "24"}):
            second = el.total_lanes()
        self.assertEqual((first, second), (12, 24))

    def test_defaults_match_runner_when_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MAX_PARALLEL", None)
            self.assertEqual(el.total_lanes(), 12)

    def test_malformed_value_fails_soft(self):
        for junk in ("", "   ", "abc", "-1"):
            with patch.dict(os.environ, {"MAX_PARALLEL": junk}):
                self.assertGreaterEqual(el.total_lanes(), 1)

    def test_explicit_override_wins(self):
        with patch.dict(os.environ, {"MAX_PARALLEL": "12"}):
            el.set_total_lanes(40)
            self.assertEqual(el.total_lanes(), 40)

    def test_override_rejects_junk_and_reverts(self):
        el.set_total_lanes("not-a-number")
        with patch.dict(os.environ, {"MAX_PARALLEL": "12"}):
            self.assertEqual(el.total_lanes(), 12)

    def test_override_is_cleared_by_invalidate(self):
        el.set_total_lanes(99)
        el.invalidate()
        with patch.dict(os.environ, {"MAX_PARALLEL": "12"}):
            self.assertEqual(el.total_lanes(), 12)


class CapacitySplitTest(unittest.TestCase):
    def setUp(self):
        el.invalidate()
        self.addCleanup(el.invalidate)

    def test_fifteen_percent_of_twelve_is_one_lane_not_six(self):
        with patch.dict(os.environ, {"MAX_PARALLEL": "12",
                                     "ORCH_EXPRESS_LANE_CAPACITY_PCT": "15"}):
            self.assertEqual(el.express_lane_capacity(), 1)  # was 6 (50% of the box)

    def test_split_sums_to_total(self):
        for total in ("4", "12", "24", "40"):
            with patch.dict(os.environ, {"MAX_PARALLEL": total,
                                         "ORCH_EXPRESS_LANE_CAPACITY_PCT": "15"}):
                self.assertEqual(el.express_lane_capacity() + el.standard_lane_capacity(),
                                 int(total), f"MAX_PARALLEL={total}")

    def test_standard_capacity_is_never_negative(self):
        for pct in ("0", "15", "50", "99", "100"):
            with patch.dict(os.environ, {"MAX_PARALLEL": "12",
                                         "ORCH_EXPRESS_LANE_CAPACITY_PCT": pct}):
                self.assertGreaterEqual(el.standard_lane_capacity(), 0, f"pct={pct}")

    def test_hundred_percent_still_leaves_a_standard_lane(self):
        # Reserving the whole machine for express work is a deadlock, not a priority.
        with patch.dict(os.environ, {"MAX_PARALLEL": "12",
                                     "ORCH_EXPRESS_LANE_CAPACITY_PCT": "100"}):
            self.assertEqual(el.express_lane_capacity(), 11)
            self.assertEqual(el.standard_lane_capacity(), 1)

    def test_zero_percent_reserves_nothing(self):
        with patch.dict(os.environ, {"MAX_PARALLEL": "12",
                                     "ORCH_EXPRESS_LANE_CAPACITY_PCT": "0"}):
            self.assertEqual(el.express_lane_capacity(), 0)
            self.assertEqual(el.standard_lane_capacity(), 12)

    def test_disabled_reserves_nothing(self):
        with patch.dict(os.environ, {"MAX_PARALLEL": "12",
                                     "ORCH_EXPRESS_LANE_ENABLED": "false"}):
            self.assertEqual(el.express_lane_capacity(), 0)
            self.assertEqual(el.standard_lane_capacity(), 12)

    def test_single_lane_machine_does_not_divide_by_zero(self):
        with patch.dict(os.environ, {"MAX_PARALLEL": "1",
                                     "ORCH_EXPRESS_LANE_CAPACITY_PCT": "15"}):
            self.assertEqual(el.express_lane_capacity(), 1)
            self.assertEqual(el.standard_lane_capacity(), 0)


class StatsTest(unittest.TestCase):
    def setUp(self):
        el.invalidate()
        self.addCleanup(el.invalidate)

    def test_stats_reports_the_real_total(self):
        with patch.dict(os.environ, {"MAX_PARALLEL": "12",
                                     "ORCH_EXPRESS_LANE_CAPACITY_PCT": "15"}):
            snapshot = el.stats()
        self.assertEqual(snapshot["total_lanes"], 12)
        self.assertEqual(snapshot["express"]["capacity"]
                         + snapshot["standard"]["capacity"], 12)

    def test_utilization_is_measured_against_the_real_capacity(self):
        with patch.dict(os.environ, {"MAX_PARALLEL": "12",
                                     "ORCH_EXPRESS_LANE_CAPACITY_PCT": "15"}):
            el.assign_task_lane("t1", "r1", use_express=True)
            used, capacity, percent = el.express_lane_utilization()
        self.assertEqual((used, capacity), (1, 1))
        self.assertEqual(percent, 100.0)

    def test_express_lane_fills_at_the_real_capacity(self):
        with patch.dict(os.environ, {"MAX_PARALLEL": "12",
                                     "ORCH_EXPRESS_LANE_CAPACITY_PCT": "15"}):
            el.assign_task_lane("t1", "r1", use_express=True)
            use_express, reason = el.should_use_express_lane({"pinned": True, "pin_rank": 1})
        self.assertFalse(use_express)
        self.assertEqual(reason, "express_lane_full")


if __name__ == "__main__":
    unittest.main(verbosity=2)
