"""
Comprehensive tests for pricing_grid_reconstruction refactor.

Tests the extracted helper methods (_tier_capacity, _consume_tier_units),
behavior-preserving refactoring of total_cost, and new validation in cost_for_units.
Ensures the consolidation of duplicated logic maintains correctness and fixes edge cases.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pricing_grid_reconstruction import (
    PricingTier, PricingGrid, PricingGridReconstructionUtil,
)


class TestPricingTierCapacity:
    """Tests for _tier_capacity static method."""

    def test_tier_capacity_unlimited(self):
        """Unlimited tier (max_units=None) returns 0."""
        tier = PricingTier("unlimited", 1, None, 1.0)
        assert PricingTier._tier_capacity(tier) == 0

    def test_tier_capacity_limited(self):
        """Limited tier returns max - min + 1."""
        tier = PricingTier("limited", 10, 100, 1.0)
        assert PricingTier._tier_capacity(tier) == 91  # 100 - 10 + 1

    def test_tier_capacity_single_unit(self):
        """Tier with same min and max has capacity 1."""
        tier = PricingTier("single", 50, 50, 1.0)
        assert PricingTier._tier_capacity(tier) == 1

    def test_tier_capacity_zero_when_invalid(self):
        """Invalid tier (max < min) returns 0."""
        tier = PricingTier("invalid", 100, 10, 1.0)
        assert PricingTier._tier_capacity(tier) == 0

    def test_tier_capacity_edge_case_large_range(self):
        """Large range capacity calculation."""
        tier = PricingTier("large", 1, 1000000, 1.0)
        assert PricingTier._tier_capacity(tier) == 1000000


class TestConsumeUnits:
    """Tests for _consume_tier_units static method."""

    def test_consume_zero_remaining(self):
        """Zero remaining units returns 0 consumed, 0 cost."""
        tier = PricingTier("test", 1, 100, 2.0)
        consumed, cost = PricingGrid._consume_tier_units(tier, 0)
        assert consumed == 0
        assert cost == 0.0

    def test_consume_negative_remaining(self):
        """Negative remaining units returns 0 consumed, 0 cost."""
        tier = PricingTier("test", 1, 100, 2.0)
        consumed, cost = PricingGrid._consume_tier_units(tier, -10)
        assert consumed == 0
        assert cost == 0.0

    def test_consume_from_unlimited_tier(self):
        """Unlimited tier consumes all remaining units."""
        tier = PricingTier("unlimited", 1, None, 2.0)
        consumed, cost = PricingGrid._consume_tier_units(tier, 50)
        assert consumed == 50
        assert cost == 100.0

    def test_consume_from_limited_tier_full(self):
        """Limited tier with remaining > capacity consumes up to max."""
        tier = PricingTier("limited", 1, 10, 2.0)
        consumed, cost = PricingGrid._consume_tier_units(tier, 100)
        # capacity = 10 - 1 + 1 = 10
        assert consumed == 10
        assert cost == 20.0

    def test_consume_from_limited_tier_partial(self):
        """Limited tier with remaining < capacity consumes exactly remaining."""
        tier = PricingTier("limited", 1, 100, 2.0)
        consumed, cost = PricingGrid._consume_tier_units(tier, 30)
        assert consumed == 30
        assert cost == 60.0

    def test_consume_with_flat_fee(self):
        """Consumption includes flat fee."""
        tier = PricingTier("premium", 1, 100, 2.0, flat_fee=50.0)
        consumed, cost = PricingGrid._consume_tier_units(tier, 25)
        assert consumed == 25
        assert cost == 100.0  # 50 flat + 25 * 2.0

    def test_consume_high_unit_start(self):
        """Tier starting at high unit count consumes correctly."""
        tier = PricingTier("high", 1000, 2000, 1.5)
        consumed, cost = PricingGrid._consume_tier_units(tier, 100)
        # capacity = 2000 - 1000 + 1 = 1001
        assert consumed == 100
        assert cost == 150.0

    def test_consume_partial_from_high_start_tier(self):
        """High-start tier with limited remaining."""
        tier = PricingTier("high", 500, 600, 3.0)
        consumed, cost = PricingGrid._consume_tier_units(tier, 50)
        # capacity = 600 - 500 + 1 = 101
        assert consumed == 50
        assert cost == 150.0


class TestCostForUnitsEdgeCases:
    """Tests for cost_for_units refactored behavior."""

    def test_cost_below_min_units(self):
        """Units below min_units returns 0."""
        tier = PricingTier("test", 100, 200, 1.0)
        assert tier.cost_for_units(50) == 0.0
        assert tier.cost_for_units(99) == 0.0

    def test_cost_at_min_units(self):
        """Units at min_units returns cost for 1 unit."""
        tier = PricingTier("test", 100, 200, 1.0)
        # applicable = min(100, 200) - 100 + 1 = 1
        assert tier.cost_for_units(100) == 1.0

    def test_cost_above_max_units_fixed(self):
        """Units above max_units returns 0 (new validation)."""
        tier = PricingTier("test", 1, 100, 2.0)
        assert tier.cost_for_units(101) == 0.0
        assert tier.cost_for_units(1000) == 0.0

    def test_cost_within_range(self):
        """Units within [min_units, max_units] calculated correctly."""
        tier = PricingTier("test", 10, 50, 2.0)
        # applicable = min(30, 50) - 10 + 1 = 21
        assert tier.cost_for_units(30) == 42.0

    def test_cost_at_max_units(self):
        """Units at max_units returns cost for max."""
        tier = PricingTier("test", 10, 50, 2.0)
        # applicable = min(50, 50) - 10 + 1 = 41
        assert tier.cost_for_units(50) == 82.0

    def test_cost_with_flat_fee_below_min(self):
        """Flat fee not charged when units below min."""
        tier = PricingTier("test", 100, 200, 2.0, flat_fee=50.0)
        assert tier.cost_for_units(50) == 0.0

    def test_cost_with_flat_fee_in_range(self):
        """Flat fee included in cost when units in range."""
        tier = PricingTier("test", 1, 100, 2.0, flat_fee=50.0)
        # applicable = min(50, 100) - 1 + 1 = 50
        assert tier.cost_for_units(50) == 150.0  # 50 + 50*2

    def test_cost_unlimited_tier(self):
        """Unlimited tier (max_units=None) calculated correctly."""
        tier = PricingTier("unlimited", 1, None, 1.5)
        assert tier.cost_for_units(100) == 150.0


class TestTotalCostRefactored:
    """Tests for total_cost using refactored _consume_tier_units."""

    def test_total_cost_single_tier(self):
        """Single tier cost calculation preserved."""
        grid = PricingGrid("p1", tiers=[
            PricingTier("flat", 1, None, 1.5),
        ])
        assert grid.total_cost(10) == 15.0

    def test_total_cost_multi_tier_sequential(self):
        """Multiple tiers consumed sequentially."""
        grid = PricingGrid("p2", tiers=[
            PricingTier("basic", 1, 10, 2.0),
            PricingTier("pro", 11, 100, 1.0),
        ])
        # 10 units at 2.0 + 5 units at 1.0 = 25.0
        assert grid.total_cost(15) == 25.0

    def test_total_cost_three_tiers(self):
        """Three-tier pricing grid."""
        grid = PricingGrid("p3", tiers=[
            PricingTier("starter", 1, 10, 3.0),
            PricingTier("growth", 11, 50, 2.0),
            PricingTier("enterprise", 51, None, 1.0),
        ])
        # 10 at 3.0 + 40 at 2.0 + 50 at 1.0 = 30 + 80 + 50 = 160
        assert grid.total_cost(100) == 160.0

    def test_total_cost_zero_units(self):
        """Zero units returns zero cost."""
        grid = PricingGrid("p4", tiers=[
            PricingTier("any", 1, 100, 5.0),
        ])
        assert grid.total_cost(0) == 0.0

    def test_total_cost_exhausts_one_tier(self):
        """Total units exactly exhaust first tier."""
        grid = PricingGrid("p5", tiers=[
            PricingTier("tier1", 1, 10, 2.0),
            PricingTier("tier2", 11, 20, 1.0),
        ])
        # exactly 10 units in first tier
        assert grid.total_cost(10) == 20.0

    def test_total_cost_partial_last_tier(self):
        """Partial consumption of last unlimited tier."""
        grid = PricingGrid("p6", tiers=[
            PricingTier("basic", 1, 5, 5.0),
            PricingTier("enterprise", 6, None, 1.0),
        ])
        # 5 at 5.0 + 10 at 1.0 = 25 + 10 = 35
        assert grid.total_cost(15) == 35.0

    def test_total_cost_with_flat_fees(self):
        """Multiple tiers with flat fees."""
        grid = PricingGrid("p7", tiers=[
            PricingTier("start", 1, 10, 2.0, flat_fee=10.0),
            PricingTier("pro", 11, None, 1.0, flat_fee=20.0),
        ])
        # tier1: 10 + 10*2 = 30; tier2: 20 + 10*1 = 30; total = 60
        assert grid.total_cost(20) == 60.0

    def test_total_cost_rounding(self):
        """Total cost rounded to 2 decimal places."""
        grid = PricingGrid("p8", tiers=[
            PricingTier("frac", 1, None, 0.333),
        ])
        cost = grid.total_cost(10)
        # 10 * 0.333 = 3.33
        assert cost == round(10 * 0.333, 2)

    def test_total_cost_unsorted_tiers_auto_sorted(self):
        """Tiers auto-sorted during construction."""
        grid = PricingGrid("p9", tiers=[
            PricingTier("pro", 11, 100, 1.0),
            PricingTier("basic", 1, 10, 2.0),
        ])
        # Tiers are sorted during __init__, then cost calculated correctly
        assert grid.total_cost(15) == 25.0


class TestGridValidationWithConsume:
    """Tests for validate_grid using _consume_tier_units logic."""

    def test_validate_valid_multi_tier(self):
        """Valid multi-tier grid passes validation."""
        grid = PricingGrid("p", tiers=[
            PricingTier("basic", 1, 10, 1.0),
            PricingTier("pro", 11, 100, 0.5),
        ])
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert valid is True
        assert issues == []

    def test_validate_empty_grid(self):
        """Empty grid flagged as invalid."""
        grid = PricingGrid("p", tiers=[])
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert valid is False
        assert "no tiers" in issues[0]

    def test_validate_negative_price(self):
        """Negative unit price flagged."""
        grid = PricingGrid("p", tiers=[
            PricingTier("bad", 1, 10, -1.0),
        ])
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert valid is False
        assert "negative" in issues[0]

    def test_validate_max_less_than_min(self):
        """Max < min flagged."""
        grid = PricingGrid("p", tiers=[
            PricingTier("bad", 100, 10, 1.0),
        ])
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert valid is False
        assert "max < min" in issues[0]

    def test_validate_overlapping_tiers(self):
        """Overlapping tier ranges flagged."""
        grid = PricingGrid("p", tiers=[
            PricingTier("tier1", 1, 100, 1.0),
            PricingTier("tier2", 50, 150, 0.5),  # overlaps tier1
        ])
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert valid is False
        assert "overlaps" in issues[0]

    def test_validate_adjacent_tiers(self):
        """Adjacent non-overlapping tiers pass."""
        grid = PricingGrid("p", tiers=[
            PricingTier("tier1", 1, 100, 1.0),
            PricingTier("tier2", 101, 200, 0.5),
        ])
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert valid is True

    def test_validate_multiple_issues(self):
        """Multiple issues reported together."""
        grid = PricingGrid("p", tiers=[
            PricingTier("bad1", 1, 10, -1.0),
            PricingTier("bad2", 100, 10, 1.0),
        ])
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert valid is False
        assert len(issues) >= 2

    def test_validate_unlimited_with_others(self):
        """Unlimited tier can coexist with limited tiers."""
        grid = PricingGrid("p", tiers=[
            PricingTier("limited", 1, 100, 1.0),
            PricingTier("unlimited", 101, None, 0.5),
        ])
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert valid is True


class TestBehaviorPreservation:
    """Integration tests ensuring refactoring preserves existing behavior."""

    def test_from_raw_tiers_preserved(self):
        """from_raw_tiers produces grids with consistent sorting and costs."""
        raw = [
            {"name": "pro", "min_units": 51, "max_units": None, "unit_price": 1.0},
            {"name": "basic", "min_units": 1, "max_units": 50, "unit_price": 2.0},
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("p", raw)
        # Tiers should be sorted by min_units during construction
        assert grid.tiers[0].name == "basic"
        assert grid.tiers[1].name == "pro"
        assert grid.total_cost(100) == 150.0  # 50*2 + 50*1

    def test_tier_for_units_consistency(self):
        """tier_for_units works with refactored total_cost."""
        grid = PricingGrid("p", tiers=[
            PricingTier("basic", 1, 50, 2.0),
            PricingTier("pro", 51, None, 1.0),
        ])
        tier_25 = grid.tier_for_units(25)
        tier_100 = grid.tier_for_units(100)
        assert tier_25.name == "basic"
        assert tier_100.name == "pro"

    def test_merge_grids_with_total_cost(self):
        """Merged grid costs calculated correctly."""
        g1 = PricingGrid("p", tiers=[PricingTier("a", 1, 10, 1.0)])
        g2 = PricingGrid("p", tiers=[
            PricingTier("a", 1, 10, 1.0),
            PricingTier("b", 11, None, 0.5),
        ])
        merged = PricingGridReconstructionUtil.merge_grids([g1, g2])
        assert merged.total_cost(20) == 15.0  # 10*1 + 10*0.5


class TestEdgeCasesAndRegressions:
    """Tests for edge cases and potential regression points."""

    def test_extreme_large_unit_count(self):
        """Large unit counts handled without overflow."""
        grid = PricingGrid("p", tiers=[
            PricingTier("flat", 1, None, 0.001),
        ])
        cost = grid.total_cost(1000000)
        assert cost == 1000.0

    def test_very_small_unit_price(self):
        """Very small unit prices rounded correctly."""
        grid = PricingGrid("p", tiers=[
            PricingTier("tiny", 1, None, 0.00001),
        ])
        cost = grid.total_cost(1000000)
        assert isinstance(cost, float)
        assert cost == 10.0

    def test_mixed_zero_and_nonzero_prices(self):
        """Tier with zero unit price handled correctly."""
        grid = PricingGrid("p", tiers=[
            PricingTier("free", 1, 10, 0.0),
            PricingTier("paid", 11, None, 1.0),
        ])
        assert grid.total_cost(20) == 10.0

    def test_single_unit_single_tier(self):
        """Single unit, single tier case."""
        grid = PricingGrid("p", tiers=[
            PricingTier("solo", 1, 1, 5.0),
        ])
        assert grid.total_cost(1) == 5.0

    def test_capacity_calculation_consistency(self):
        """_tier_capacity matches actual consumption in _consume_tier_units."""
        tier = PricingTier("test", 10, 100, 1.0)
        capacity = PricingTier._tier_capacity(tier)
        consumed, _ = PricingGrid._consume_tier_units(tier, capacity + 100)
        # Should consume at most capacity units
        assert consumed == capacity
