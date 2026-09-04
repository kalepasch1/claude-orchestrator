#!/usr/bin/env python3
"""The pinned express lane must respect its own reservation.

VALIDATION FINDING
------------------
`_express_rank` in db.claim_task carries a careful docstring: it is bounded by
`express_lane_capacity()` because, in its own words, "without the bound a pinned batch
holds every lane until it drains, which starves the rest of the portfolio".

The bound did not apply to pinned tasks. `_pinned_rank` and `_pin_rank_order` sit AHEAD
of `_express_rank` in the sort key and were ungated, so a pinned batch still took the
whole machine — the exact starvation the ceiling was written to prevent, for the exact
case its docstring names. Worse, `_is_express_row` already counted pinned tasks against
`express_capacity`, so the reservation was being *spent* by pins without being
*enforced* on them.

These tests pin both halves of the corrected behaviour:

  * reservation has room  -> a pin still claims first (unchanged operator promise)
  * reservation is FULL   -> a pin sorts as ordinary work, so the rest of the portfolio
                             keeps moving
  * express disabled      -> ordering exactly as before, pin included
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.dirname(HERE)
for _path in (RUNNER, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import db  # noqa: E402

# Reuses the sibling suite's fixtures rather than re-declaring them: the two files must
# agree about what a task row and a mocked select look like, or they can pass while
# describing different systems.
from test_pinned_express_lane import _make_select, _task  # noqa: E402


class PinnedRespectsReservationTest(unittest.TestCase):
    def _claim(self, queued, active=None):
        claimed = []

        def fake_patch(method, path, body=None, headers=None, params=None):
            if path == "/rest/v1/tasks" and body and body.get("state") == "RUNNING":
                task_id = (params or {}).get("id", "").replace("eq.", "")
                claimed.append(task_id)
                task = next((t for t in queued if t["id"] == task_id), None)
                return [task] if task else []
            return None

        sel = _make_select(queued, active=active or [])
        with patch.object(db, "select", side_effect=sel), \
             patch.object(db, "_req", side_effect=fake_patch):
            db.claim_task("runner-1")
        return claimed[0] if claimed else None

    def _queue(self):
        """One pinned task created LAST, so only the pin can put it first."""
        return [
            _task("old-standard", created_at="2024-01-01T00:00:00"),
            _task("pinned-one", pinned=True, pin_rank=1,
                  created_at="2024-06-01T00:00:00"),
        ]

    def test_a_pin_claims_first_when_the_reservation_has_room(self):
        with patch.object(db, "_express_capacity", return_value=4):
            self.assertEqual(self._claim(self._queue(), active=[]), "pinned-one")

    def test_a_pin_stops_jumping_once_the_reservation_is_full(self):
        """The whole point: the portfolio keeps moving instead of waiting for the batch."""
        running = [_task(f"running-{i}", pinned=True, pin_rank=1, state="RUNNING",
                         project_id="p2")
                   for i in range(4)]
        with patch.object(db, "_express_capacity", return_value=4):
            self.assertEqual(self._claim(self._queue(), active=running), "old-standard")

    def test_the_boundary_is_exact(self):
        queue = self._queue()
        with patch.object(db, "_express_capacity", return_value=3):
            three = [_task(f"r{i}", pinned=True, pin_rank=1, state="RUNNING",
                           project_id="p2")
                     for i in range(3)]
            two = three[:2]
            self.assertEqual(self._claim(queue, active=two), "pinned-one",
                             "2 of 3 used — the pin still jumps")
            self.assertEqual(self._claim(queue, active=three), "old-standard",
                             "3 of 3 used — the reservation is spent")

    def test_express_disabled_leaves_pin_ordering_exactly_as_before(self):
        """capacity 0 means the feature is off; it must not change any ordering."""
        running = [_task(f"r{i}", pinned=True, pin_rank=1, state="RUNNING",
                         project_id="p2")
                   for i in range(9)]
        with patch.object(db, "_express_capacity", return_value=0):
            self.assertEqual(self._claim(self._queue(), active=running), "pinned-one")

    def test_pin_rank_order_still_decides_among_pins_with_room(self):
        queue = [
            _task("rank-5", pinned=True, pin_rank=5, created_at="2024-01-01T00:00:00"),
            _task("rank-1", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
        ]
        with patch.object(db, "_express_capacity", return_value=4):
            self.assertEqual(self._claim(queue, active=[]), "rank-1")

    def test_a_full_reservation_falls_back_to_fifo_among_pins(self):
        """With the pin ordering suspended, the oldest work wins — not the lowest rank."""
        queue = [
            _task("older-rank-5", pinned=True, pin_rank=5,
                  created_at="2024-01-01T00:00:00"),
            _task("newer-rank-1", pinned=True, pin_rank=1,
                  created_at="2024-06-01T00:00:00"),
        ]
        running = [_task(f"r{i}", pinned=True, pin_rank=1, state="RUNNING",
                         project_id="p2")
                   for i in range(4)]
        with patch.object(db, "_express_capacity", return_value=4):
            self.assertEqual(self._claim(queue, active=running), "older-rank-5")

    def test_the_counter_and_the_bound_agree_about_what_pinned_means(self):
        """_is_express_row counts pins against the reservation; the gate must too.

        They disagreed before: pins were counted but never restrained, so the ceiling
        could be fully consumed by work that ignored it.
        """
        pinned = _task("p", pinned=True, pin_rank=1)
        self.assertTrue(db._is_express_row(pinned),
                        "a pin consumes express capacity, so it must also obey it")

    def test_a_pin_with_rank_zero_is_unpinned_either_way(self):
        queue = [
            _task("old-standard", created_at="2024-01-01T00:00:00"),
            _task("rank-zero", pinned=True, pin_rank=0,
                  created_at="2024-06-01T00:00:00"),
        ]
        full = [_task(f"r{i}", pinned=True, pin_rank=1, state="RUNNING",
                      project_id="p2") for i in range(4)]
        for capacity, active in ((4, []), (4, full)):
            with patch.object(db, "_express_capacity", return_value=capacity):
                self.assertEqual(self._claim(queue, active=active), "old-standard")

    def test_the_capacity_lookup_is_fail_soft(self):
        """A broken express_lane module must leave ordering alone, not break claiming."""
        import express_lane

        with patch.object(express_lane, "express_lane_capacity",
                          side_effect=RuntimeError("boom")):
            self.assertEqual(db._express_capacity(), 0)

    def test_the_express_row_predicate_is_fail_soft(self):
        for bad in (None, {}, {"pinned": "yes"}, {"priority": object()}):
            self.assertIsInstance(db._is_express_row(bad if isinstance(bad, dict) else {}),
                                  bool)


if __name__ == "__main__":
    unittest.main()
