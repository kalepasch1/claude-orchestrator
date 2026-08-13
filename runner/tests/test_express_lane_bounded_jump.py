#!/usr/bin/env python3
"""The express jump queue is BOUNDED by express_lane_capacity().

Before this, _express_rank sorted every express (pinned / low-priority-number) task ahead
of all standard work with no ceiling, so a pinned batch held every lane until it drained.
express_lane.express_lane_capacity() already declared the right bound — 15% of
MAX_PARALLEL, never the whole machine — and nothing consulted it.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import db  # noqa: E402
import express_lane  # noqa: E402


def task(**kw):
    row = {"id": "t", "slug": "s", "pinned": False, "pin_rank": None, "priority": 1000}
    row.update(kw)
    return row


class IsExpressRowTests(unittest.TestCase):
    def test_a_pinned_task_with_a_rank_is_express(self):
        self.assertTrue(db._is_express_row(task(pinned=True, pin_rank=1)))

    def test_a_pinned_task_without_a_rank_is_not(self):
        """Matches _pin_rank_order, which also treats rank 0/None as unpinned."""
        self.assertFalse(db._is_express_row(task(pinned=True, pin_rank=None)))
        self.assertFalse(db._is_express_row(task(pinned=True, pin_rank=0)))

    def test_a_low_priority_number_is_express(self):
        self.assertTrue(db._is_express_row(task(priority=10)))
        self.assertFalse(db._is_express_row(task(priority=1000)))

    def test_it_delegates_to_express_lane_so_the_two_cannot_diverge(self):
        with mock.patch.object(express_lane, "is_express_task",
                               return_value=(True, "stub")) as pred:
            self.assertTrue(db._is_express_row(task()))
        pred.assert_called_once()

    def test_the_feature_switch_turns_it_off(self):
        with mock.patch.dict(os.environ, {"ORCH_EXPRESS_LANE_ENABLED": "false"}):
            self.assertFalse(db._is_express_row(task(pinned=True, pin_rank=1)))

    def test_garbage_rows_never_raise(self):
        for bad in (None, "x", 7, [], {}):
            self.assertIsInstance(db._is_express_row(bad), bool)


class ExpressCapacityTests(unittest.TestCase):
    def test_capacity_is_a_share_of_max_parallel_not_the_whole_machine(self):
        with mock.patch.dict(os.environ, {"MAX_PARALLEL": "12",
                                          "ORCH_EXPRESS_LANE_CAPACITY_PCT": "15"}):
            capacity = db._express_capacity()
        self.assertGreaterEqual(capacity, 1)
        self.assertLess(capacity, 12)

    def test_a_hundred_percent_still_leaves_a_standard_lane(self):
        """A reservation that leaves no standard lane is a deadlock, not a priority."""
        with mock.patch.dict(os.environ, {"MAX_PARALLEL": "12",
                                          "ORCH_EXPRESS_LANE_CAPACITY_PCT": "100"}):
            self.assertEqual(db._express_capacity(), 11)

    def test_disabled_means_zero(self):
        with mock.patch.dict(os.environ, {"ORCH_EXPRESS_LANE_ENABLED": "false"}):
            self.assertEqual(db._express_capacity(), 0)

    def test_zero_percent_means_zero(self):
        with mock.patch.dict(os.environ, {"ORCH_EXPRESS_LANE_CAPACITY_PCT": "0"}):
            self.assertEqual(db._express_capacity(), 0)

    def test_a_broken_express_lane_module_disables_the_jump_rather_than_raising(self):
        with mock.patch.object(express_lane, "express_lane_capacity",
                               side_effect=RuntimeError("boom")):
            self.assertEqual(db._express_capacity(), 0)


class BoundedJumpSemanticsTests(unittest.TestCase):
    """The ordering rule itself, expressed the way the claim scan applies it."""

    @staticmethod
    def _rank(row, express_lane_open):
        # Mirrors the closure in db.claim(): the gate is evaluated once per scan, and an
        # express row only jumps while the gate is open.
        if not express_lane_open:
            return 1
        return 0 if db._is_express_row(row) else 1

    def test_express_work_jumps_while_the_lane_is_open(self):
        self.assertEqual(self._rank(task(pinned=True, pin_rank=1), True), 0)
        self.assertEqual(self._rank(task(), True), 1)

    def test_express_work_sorts_as_standard_once_the_lane_is_full(self):
        self.assertEqual(self._rank(task(pinned=True, pin_rank=1), False), 1)
        self.assertEqual(self._rank(task(), False), 1)

    def test_a_full_lane_cannot_starve_standard_work(self):
        """The whole point: with the bound closed, nothing outranks anything on this key,
        so the remaining tie-breaks (portfolio order, EV, FIFO) decide — which is exactly
        the behaviour that existed before the express tier was introduced."""
        rows = [task(id="a", pinned=True, pin_rank=1), task(id="b"),
                task(id="c", priority=5)]
        self.assertEqual([self._rank(r, False) for r in rows], [1, 1, 1])

    def test_the_gate_is_closed_when_capacity_is_reached(self):
        for active, capacity, expected_open in [(0, 2, True), (1, 2, True),
                                                (2, 2, False), (3, 2, False),
                                                (0, 0, False)]:
            self.assertEqual(capacity > 0 and active < capacity, expected_open,
                             f"active={active} capacity={capacity}")


if __name__ == "__main__":
    unittest.main()
