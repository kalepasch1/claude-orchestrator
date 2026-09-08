"""The build limit was a count. The resource it was protecting is memory.

WHAT THIS IS FOR. Measured on the fleet host 2026-09-08: swap 44.67 GB used of 46 GB,
18,006,808 swapouts, 12,808,554 swapins, a 1-minute load average of 55 with only 14 of
772 processes runnable. That is a machine paging, not computing. One `nuxt build` held
4.52 GB resident, and the slot limit permitted two of them.

The memory floor in hold() was never broken -- checked live that day, it reported free
3.7 GB against a 4.0 GB floor and correctly refused the slot. What it could not do was
stop the SECOND build, because max_concurrent() was a constant. The floor makes a build
WAIT, and after wait_budget_s() every caller proceeds anyway, deliberately: "a slow build
beats a false BUILDFAIL". That is right for slot contention and wrong for memory. Every
one of the six callers uses `with build_slots.hold(...)` without binding the result, so
the design fails open by construction and the yielded boolean cannot carry a refusal.

So the ceiling became min(operator's count, what free memory affords). The tests below
pin that, and pin the two ways it could go wrong: returning zero, which would stop the
fleet building at all, and inventing a restriction on a host where memory cannot be read.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_slots

#: Free-memory readings either side of a 4.0 GB per-build budget.
ROOMY_GB = 20.0
ENOUGH_FOR_ONE_GB = 5.0
THE_MEASURED_PRESSURE_GB = 3.7        # what the host actually reported that day
NOTHING_LEFT_GB = 0.2
ONE_BUILD = 1
TWO_BUILDS = 2


class TheCeilingFollowsFreeMemory(unittest.TestCase):

    def test_a_roomy_machine_gets_the_operators_full_count(self):
        with patch.object(build_slots, "free_gb", return_value=ROOMY_GB):
            self.assertEqual(build_slots.max_concurrent(),
                             build_slots.configured_max_concurrent())

    def test_the_measured_pressure_narrows_two_builds_to_one(self):
        """3.7 GB free against a 4.0 GB per-build budget: one build, not two.

        This is the exact reading from the host on 2026-09-08.
        """
        with patch.object(build_slots, "free_gb", return_value=THE_MEASURED_PRESSURE_GB):
            self.assertEqual(build_slots.max_concurrent(), ONE_BUILD)

    def test_room_for_exactly_one_build_yields_exactly_one(self):
        with patch.object(build_slots, "free_gb", return_value=ENOUGH_FOR_ONE_GB):
            self.assertEqual(build_slots.max_concurrent(), ONE_BUILD)

    def test_it_never_returns_zero_however_bad_things_get(self):
        """A fleet that will not build AT ALL is a worse outage than a slow one."""
        with patch.object(build_slots, "free_gb", return_value=NOTHING_LEFT_GB):
            self.assertEqual(build_slots.max_concurrent(), ONE_BUILD)

    def test_it_never_exceeds_the_operators_ceiling(self):
        """Memory may only narrow the limit, never widen it past what was configured."""
        with patch.dict(os.environ, {"ORCH_MAX_CONCURRENT_BUILDS": str(TWO_BUILDS)}), \
             patch.object(build_slots, "free_gb", return_value=ROOMY_GB):
            self.assertEqual(build_slots.max_concurrent(), TWO_BUILDS)

    def test_an_unmeasurable_machine_gets_no_invented_restriction(self):
        """free_gb() returns None where it cannot read memory. Do not guess downward."""
        with patch.object(build_slots, "free_gb", return_value=None):
            self.assertEqual(build_slots.max_concurrent(),
                             build_slots.configured_max_concurrent())


class TheSlotFilesFollowTheCeiling(unittest.TestCase):

    def test_fewer_slot_paths_are_offered_under_pressure(self):
        """Narrowing works by offering fewer slots, which is why it is safe mid-build.

        A holder of a higher-numbered slot keeps it until it releases; the cap applies
        to the next build, never to a running one.
        """
        with patch.dict(os.environ, {"ORCH_MAX_CONCURRENT_BUILDS": str(TWO_BUILDS)}):
            with patch.object(build_slots, "free_gb", return_value=ROOMY_GB):
                roomy = build_slots._slot_paths()
            with patch.object(build_slots, "free_gb",
                              return_value=THE_MEASURED_PRESSURE_GB):
                tight = build_slots._slot_paths()
        self.assertEqual(len(roomy), TWO_BUILDS)
        self.assertEqual(len(tight), ONE_BUILD)
        self.assertEqual(tight[0], roomy[0], "the surviving slot must be the same file")


class TheBudgetIsConfigurable(unittest.TestCase):

    def test_a_bad_override_falls_back_rather_than_raising(self):
        with patch.dict(os.environ, {"ORCH_BUILD_MEMORY_BUDGET_GB": "not-a-number"}):
            self.assertEqual(build_slots.build_memory_budget_gb(),
                             build_slots.DEFAULT_BUILD_MEMORY_BUDGET_GB)

    def test_a_smaller_budget_allows_more_builds(self):
        """An operator who knows their builds are cheap can say so."""
        with patch.dict(os.environ, {"ORCH_MAX_CONCURRENT_BUILDS": str(TWO_BUILDS),
                                     "ORCH_BUILD_MEMORY_BUDGET_GB": "1.0"}), \
             patch.object(build_slots, "free_gb",
                          return_value=THE_MEASURED_PRESSURE_GB):
            self.assertEqual(build_slots.max_concurrent(), TWO_BUILDS)


if __name__ == "__main__":
    unittest.main()
