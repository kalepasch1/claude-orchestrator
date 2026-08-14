#!/usr/bin/env python3
"""An exact duplicate tier made a correct price table fail its own validation.

`from_raw_tiers` kept every raw entry, so a feed listing the same tier twice produced a
grid holding it twice — and an exact duplicate overlaps ITSELF, so `validate_grid`
returned (False, ["tier 'base' overlaps with 'base'"]) for a table that was actually
fine. It also inflated the tier count everywhere the grid is rendered or counted.

The regression guard is the pair: duplicates go, and NOTHING ELSE changes — same cost,
same ordering, and a same-named tier at a different price is still preserved and still
reported as a real overlap.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pricing_grid_reconstruction import PricingGridReconstructionUtil as Util

BASE = {"name": "base", "min_units": 1, "max_units": 10, "unit_price": 2.0}
MID = {"name": "mid", "min_units": 11, "max_units": 50, "unit_price": 1.5}


class TestDuplicateRemoval(unittest.TestCase):
    def test_exact_duplicate_is_dropped(self):
        grid = Util.from_raw_tiers("p", [dict(BASE), dict(BASE)])
        self.assertEqual(len(grid.tiers), 1)
        self.assertEqual([t.name for t in grid.tiers], ["base"])

    def test_a_deduped_grid_passes_its_own_validation(self):
        """The observable harm: a redundant row failed validate_grid."""
        grid = Util.from_raw_tiers("p", [dict(BASE), dict(BASE)])
        ok, issues = Util.validate_grid(grid)
        self.assertTrue(ok, issues)
        self.assertEqual(issues, [])

    def test_many_copies_collapse_to_one(self):
        grid = Util.from_raw_tiers("p", [dict(BASE) for _ in range(5)])
        self.assertEqual(len(grid.tiers), 1)

    def test_duplicates_among_distinct_tiers_are_removed_without_losing_the_others(self):
        grid = Util.from_raw_tiers("p", [dict(BASE), dict(MID), dict(BASE)])
        self.assertEqual([t.name for t in grid.tiers], ["base", "mid"])


class TestNothingElseChanges(unittest.TestCase):
    def test_cost_is_identical_with_and_without_the_duplicate(self):
        # `_consume_tier_units` already consumed each unit once, so the duplicate never
        # affected price. Removing it must not move the number either.
        unique = Util.from_raw_tiers("p", [dict(BASE), dict(MID)])
        dupey = Util.from_raw_tiers("p", [dict(BASE), dict(MID), dict(BASE)])
        for units in (1, 5, 10, 11, 30, 50):
            with self.subTest(units=units):
                self.assertEqual(dupey.total_cost(units), unique.total_cost(units))

    def test_distinct_tiers_are_untouched(self):
        grid = Util.from_raw_tiers("p", [dict(MID), dict(BASE)])
        self.assertEqual(len(grid.tiers), 2)

    def test_sort_order_is_still_applied(self):
        grid = Util.from_raw_tiers("p", [dict(MID), dict(BASE), dict(MID)])
        self.assertEqual([t.name for t in grid.tiers], ["base", "mid"])

    def test_same_name_different_price_is_NOT_a_duplicate(self):
        """Dedup keys on the full pricing identity, not the label.

        Collapsing these would silently discard a real price and hide a genuine
        misconfiguration — the overlap must still be reported.
        """
        cheap = dict(BASE)
        pricey = dict(BASE, unit_price=9.0)
        grid = Util.from_raw_tiers("p", [cheap, pricey])
        self.assertEqual(len(grid.tiers), 2)
        ok, issues = Util.validate_grid(grid)
        self.assertFalse(ok)
        self.assertTrue(issues)

    def test_same_name_different_bounds_is_NOT_a_duplicate(self):
        grid = Util.from_raw_tiers("p", [dict(BASE), dict(BASE, max_units=20)])
        self.assertEqual(len(grid.tiers), 2)

    def test_empty_and_single_inputs_still_work(self):
        self.assertEqual(len(Util.from_raw_tiers("p", []).tiers), 0)
        self.assertEqual(len(Util.from_raw_tiers("p", [dict(BASE)]).tiers), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
