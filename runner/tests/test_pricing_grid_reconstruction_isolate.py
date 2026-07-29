"""Isolated test cases for pricing grid reconstruction duplicate and boundary edge cases.

This module isolates specific test scenarios that arise from:
1. Duplicate tier elimination and normalization
2. Unit boundary calculation edge cases
3. Multi-tier cost computation with overlapping ranges
4. Tier selection at exact boundary transitions
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pricing_grid_reconstruction import (
    PricingTier, PricingGrid, PricingGridReconstructionUtil,
)


class TestBoundaryCalculationEdgeCases:
    """Edge cases in unit boundary calculations where off-by-one errors commonly occur."""

    def test_tier_cost_exact_min_boundary(self):
        """Test cost calculation at exact minimum unit boundary."""
        tier = PricingTier(name="basic", min_units=10, max_units=100, unit_price=2.0)
        # At min_units=10, should include 1 unit
        cost = tier.cost_for_units(10)
        assert cost == 2.0, f"Expected 2.0 (1 unit * 2.0), got {cost}"

    def test_tier_cost_exact_max_boundary(self):
        """Test cost calculation at exact maximum unit boundary."""
        tier = PricingTier(name="pro", min_units=10, max_units=100, unit_price=1.5)
        # At max_units=100, should count all units from min to max (91 units)
        cost = tier.cost_for_units(100)
        assert cost == 136.5, f"Expected 136.5 (91 units * 1.5), got {cost}"

    def test_tier_cost_below_min_boundary(self):
        """Test cost calculation below minimum unit boundary."""
        tier = PricingTier(name="basic", min_units=10, max_units=100, unit_price=2.0)
        # Below min_units should return 0
        cost = tier.cost_for_units(5)
        assert cost == 0.0, f"Expected 0.0, got {cost}"

    def test_tier_cost_above_max_boundary(self):
        """Test cost calculation above maximum unit boundary."""
        tier = PricingTier(name="basic", min_units=10, max_units=100, unit_price=2.0)
        # Above max_units returns 0 (units outside valid range [min_units, max_units])
        cost = tier.cost_for_units(150)
        assert cost == 0.0, f"Expected 0.0 (150 > max_units), got {cost}"

    def test_tier_cost_one_unit_tier(self):
        """Test tier that covers exactly one unit."""
        tier = PricingTier(name="single", min_units=50, max_units=50, unit_price=5.0)
        cost = tier.cost_for_units(50)
        assert cost == 5.0, f"Expected 5.0 (1 unit * 5.0), got {cost}"

    def test_tier_cost_one_unit_tier_adjacent_request(self):
        """Test single-unit tier with request at adjacent unit."""
        tier = PricingTier(name="single", min_units=50, max_units=50, unit_price=5.0)
        cost = tier.cost_for_units(51)
        assert cost == 0.0, f"Expected 0.0 (51 > 50), got {cost}"

    def test_tier_with_flat_fee_at_boundary(self):
        """Test flat fee application at unit boundaries."""
        tier = PricingTier(
            name="premium", min_units=1, max_units=50,
            unit_price=3.0, flat_fee=100.0
        )
        # Flat fee should apply regardless of units
        cost_at_min = tier.cost_for_units(1)
        assert cost_at_min == 103.0, f"Expected 103.0 (100 + 1*3), got {cost_at_min}"

        cost_at_max = tier.cost_for_units(50)
        assert cost_at_max == 250.0, f"Expected 250.0 (100 + 50*3), got {cost_at_max}"


class TestMultiTierBoundaryTransitions:
    """Test unit transitions between multiple tiers."""

    def test_grid_cost_exact_tier_boundary_transition(self):
        """Test cost calculation at exact transition between tiers."""
        grid = PricingGrid(product_id="multi", tiers=[
            PricingTier("starter", min_units=1, max_units=10, unit_price=10.0),
            PricingTier("growth", min_units=11, max_units=100, unit_price=5.0),
        ])
        # At unit 10: should use only starter tier
        cost_at_10 = grid.total_cost(10)
        assert cost_at_10 == 100.0, f"Expected 100.0 (10 * 10), got {cost_at_10}"

        # At unit 11: should use starter (10 units) + growth (1 unit)
        cost_at_11 = grid.total_cost(11)
        assert cost_at_11 == 105.0, f"Expected 105.0 (10*10 + 1*5), got {cost_at_11}"

    def test_grid_cost_transition_with_gap(self):
        """Test tiers with a gap in coverage (should handle as-is)."""
        grid = PricingGrid(product_id="gapped", tiers=[
            PricingTier("tier1", min_units=1, max_units=10, unit_price=1.0),
            PricingTier("tier2", min_units=20, max_units=30, unit_price=2.0),
        ])
        # Unit 15 falls in the gap: no tier applies
        # Grid should still compute for available tiers
        cost = grid.total_cost(10)
        assert cost == 10.0, f"Expected 10.0, got {cost}"

    def test_grid_tier_for_units_at_boundaries(self):
        """Test tier selection at exact boundaries."""
        grid = PricingGrid(product_id="boundaries", tiers=[
            PricingTier("basic", min_units=1, max_units=50, unit_price=1.0),
            PricingTier("pro", min_units=51, max_units=200, unit_price=0.5),
            PricingTier("enterprise", min_units=201, max_units=None, unit_price=0.25),
        ])

        # At tier boundaries
        assert grid.tier_for_units(1).name == "basic"
        assert grid.tier_for_units(50).name == "basic"
        assert grid.tier_for_units(51).name == "pro"
        assert grid.tier_for_units(200).name == "pro"
        assert grid.tier_for_units(201).name == "enterprise"
        assert grid.tier_for_units(10000).name == "enterprise"


class TestDuplicateEliminationAndNormalization:
    """Test proper handling of duplicate/overlapping tier configurations."""

    def test_from_raw_tiers_normalizes_order(self):
        """Test that raw tiers are sorted by min_units."""
        raw = [
            {"name": "high", "min_units": 100, "max_units": None, "unit_price": 0.5},
            {"name": "low", "min_units": 1, "max_units": 50, "unit_price": 2.0},
            {"name": "mid", "min_units": 51, "max_units": 99, "unit_price": 1.0},
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod", raw)

        # Should be sorted: low (1), mid (51), high (100)
        assert grid.tiers[0].name == "low"
        assert grid.tiers[1].name == "mid"
        assert grid.tiers[2].name == "high"

    def test_merge_grids_uses_most_complete(self):
        """Test that merge_grids selects grid with most tiers as base."""
        g1 = PricingGrid("p1", tiers=[
            PricingTier("a", 1, 10, 1.0),
        ])
        g2 = PricingGrid("p1", tiers=[
            PricingTier("a", 1, 10, 1.0),
            PricingTier("b", 11, None, 0.5),
        ])
        g3 = PricingGrid("p1", tiers=[
            PricingTier("a", 1, 10, 1.0),
            PricingTier("b", 11, 50, 0.5),
            PricingTier("c", 51, None, 0.25),
        ])

        merged = PricingGridReconstructionUtil.merge_grids([g1, g2, g3])
        assert len(merged.tiers) == 3
        assert merged.tiers[0].name == "a"
        assert merged.tiers[1].name == "b"
        assert merged.tiers[2].name == "c"

    def test_validate_detects_overlapping_tiers(self):
        """Test validation detects tier overlap issues."""
        grid = PricingGrid("p", tiers=[
            PricingTier("a", 1, 50, 1.0),
            PricingTier("b", 40, 100, 0.5),  # Overlaps with 'a' at 40-50
        ])
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert valid is False
        assert any("overlap" in issue for issue in issues)

    def test_validate_detects_adjacent_tiers_no_gap(self):
        """Test validation passes for properly adjacent tiers."""
        grid = PricingGrid("p", tiers=[
            PricingTier("basic", 1, 50, 2.0),
            PricingTier("pro", 51, 100, 1.0),  # Starts where basic ends + 1
        ])
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert valid is True
        assert issues == []


class TestUnlimitedTierHandling:
    """Test handling of unlimited (max_units=None) tiers."""

    def test_unlimited_tier_consumes_remaining_units(self):
        """Test that unlimited tier properly consumes all remaining units."""
        grid = PricingGrid(product_id="unlimited", tiers=[
            PricingTier("capped", min_units=1, max_units=100, unit_price=1.0),
            PricingTier("unlimited", min_units=101, max_units=None, unit_price=0.1),
        ])

        # Request 1000 units: 100 at 1.0 + 900 at 0.1
        cost = grid.total_cost(1000)
        assert cost == 190.0, f"Expected 190.0, got {cost}"

    def test_single_unlimited_tier_large_volume(self):
        """Test single unlimited tier with large volume."""
        grid = PricingGrid(product_id="volume", tiers=[
            PricingTier("all", min_units=1, max_units=None, unit_price=0.01),
        ])

        cost_1m = grid.total_cost(1_000_000)
        assert cost_1m == 10_000.0, f"Expected 10000.0, got {cost_1m}"

    def test_unlimited_tier_with_flat_fee(self):
        """Test unlimited tier with flat fee."""
        grid = PricingGrid(product_id="enterprise", tiers=[
            PricingTier(
                "ent", min_units=1, max_units=None,
                unit_price=0.01, flat_fee=500.0
            ),
        ])

        cost = grid.total_cost(100)
        assert cost == 501.0, f"Expected 501.0 (500 flat + 100*0.01), got {cost}"


class TestSpecialCasesAndRegression:
    """Regression tests for specific calculated values and edge cases."""

    def test_from_flat_price_simplicity(self):
        """Test simple flat price grid creation."""
        grid = PricingGridReconstructionUtil.from_flat_price("simple", 9.99)

        assert grid.product_id == "simple"
        assert len(grid.tiers) == 1
        tier = grid.tiers[0]
        assert tier.unit_price == 9.99
        assert tier.min_units == 1
        assert tier.max_units is None

        # Cost should scale linearly
        cost_100 = grid.total_cost(100)
        assert cost_100 == 999.0, f"Expected 999.0, got {cost_100}"

    def test_grid_total_cost_rounding(self):
        """Test that total_cost is properly rounded to 2 decimals."""
        grid = PricingGrid(product_id="rounding", tiers=[
            PricingTier("frac", min_units=1, max_units=None, unit_price=0.333),
        ])

        cost = grid.total_cost(3)
        assert cost == round(3 * 0.333, 2)
        assert isinstance(cost, float)

    def test_tier_below_min_with_flat_fee(self):
        """Test that flat fee is not applied when units below minimum."""
        tier = PricingTier(
            "premium", min_units=100, max_units=None,
            unit_price=1.0, flat_fee=50.0
        )
        cost = tier.cost_for_units(50)
        assert cost == 0.0, "Flat fee should not apply when below min_units"

    def test_grid_cost_empty_tiers_list(self):
        """Test grid with empty tiers list (edge case)."""
        grid = PricingGrid(product_id="empty", tiers=[])
        cost = grid.total_cost(100)
        assert cost == 0.0, "Empty grid should have zero cost"

    def test_metadata_preservation(self):
        """Test that tier metadata is preserved through operations."""
        raw = [
            {
                "name": "custom",
                "min_units": 1,
                "max_units": 100,
                "unit_price": 2.0,
                "metadata": {"region": "us-east", "sla": "99.9%"}
            }
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod", raw)

        assert grid.tiers[0].metadata["region"] == "us-east"
        assert grid.tiers[0].metadata["sla"] == "99.9%"

    def test_price_zero_units(self):
        """Test cost calculation for zero units (edge case)."""
        grid = PricingGrid(product_id="zero", tiers=[
            PricingTier("any", min_units=0, max_units=None, unit_price=1.0),
        ])
        cost = grid.total_cost(0)
        assert cost == 0.0

    def test_negative_max_units_validation(self):
        """Test that validation catches impossible max < min."""
        grid = PricingGrid(product_id="bad", tiers=[
            PricingTier("bad", min_units=100, max_units=10, unit_price=1.0),
        ])
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert valid is False
        assert any("max < min" in issue for issue in issues)
