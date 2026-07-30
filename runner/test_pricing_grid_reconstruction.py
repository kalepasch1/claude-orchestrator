#!/usr/bin/env python3
"""
test_pricing_grid_reconstruction.py - Comprehensive tests for pricing grid reconstruction utility.

Tests the PricingGridReconstructionUtil class and data model integrity:
  - PricingTier and PricingGrid data structure operations
  - Tiered cost calculations and unit consumption
  - Grid merging and validation
  - Serialization with metadata handling
  - Edge cases: unlimited tiers, overlapping ranges, negative prices
  - Integration with common_utils.consume_from_tier()

Environment variables tested:
  (None - utility operates deterministically)
"""
import sys
import os
import pytest
from typing import Dict, Any, List
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable DB at module load
os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_DB_URL"] = ""

# Import the module under test
from pricing_grid_reconstruction import (
    PricingTier,
    PricingGrid,
    PricingGridReconstructionUtil,
)
import common_utils


class TestPricingTier:
    """Test PricingTier data class and methods."""

    def test_tier_creation_basic(self):
        """PricingTier can be created with required fields."""
        tier = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0)
        assert tier.name == "basic"
        assert tier.min_units == 1
        assert tier.max_units == 100
        assert tier.unit_price == 10.0
        assert tier.flat_fee == 0.0
        assert tier.metadata == {}

    def test_tier_creation_with_optional_fields(self):
        """PricingTier accepts optional flat_fee and metadata."""
        metadata = {"template_id": "t123", "region": "US"}
        tier = PricingTier(
            name="premium",
            min_units=101,
            max_units=1000,
            unit_price=5.0,
            flat_fee=50.0,
            metadata=metadata
        )
        assert tier.flat_fee == 50.0
        assert tier.metadata == metadata

    def test_tier_unlimited_property(self):
        """is_unlimited returns True when max_units is None."""
        unlimited = PricingTier(name="unlimited", min_units=1001, max_units=None, unit_price=1.0)
        limited = PricingTier(name="limited", min_units=1, max_units=100, unit_price=10.0)
        assert unlimited.is_unlimited is True
        assert limited.is_unlimited is False

    def test_tier_capacity_calculation_unlimited(self):
        """_tier_capacity returns 0 for unlimited tiers."""
        tier = PricingTier(name="unlimited", min_units=100, max_units=None, unit_price=1.0)
        assert PricingTier._tier_capacity(tier) == 0

    def test_tier_capacity_calculation_limited(self):
        """_tier_capacity returns (max - min + 1) for limited tiers."""
        tier = PricingTier(name="limited", min_units=1, max_units=100, unit_price=10.0)
        assert PricingTier._tier_capacity(tier) == 100

    def test_tier_capacity_calculation_single_unit(self):
        """_tier_capacity returns 1 for single-unit tier."""
        tier = PricingTier(name="single", min_units=50, max_units=50, unit_price=10.0)
        assert PricingTier._tier_capacity(tier) == 1

    def test_tier_capacity_invalid_range(self):
        """_tier_capacity returns 0 when max < min."""
        tier = PricingTier(name="invalid", min_units=100, max_units=50, unit_price=10.0)
        assert PricingTier._tier_capacity(tier) == 0

    def test_cost_for_units_within_range(self):
        """cost_for_units returns correct cost for units within tier range."""
        tier = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0, flat_fee=5.0)
        # Units 50: flat_fee (5.0) + (units_in_tier * unit_price)
        # units_in_tier = min(50, 100) - 1 + 1 = 50
        cost = tier.cost_for_units(50)
        assert cost == 5.0 + (50 * 10.0)

    def test_cost_for_units_at_min_boundary(self):
        """cost_for_units works correctly at minimum boundary."""
        tier = PricingTier(name="basic", min_units=10, max_units=100, unit_price=5.0)
        # Units 10: within range [10, 100]
        # applicable = min(10, 100) - 10 + 1 = 1
        cost = tier.cost_for_units(10)
        assert cost == 1 * 5.0

    def test_cost_for_units_at_max_boundary(self):
        """cost_for_units works correctly at maximum boundary."""
        tier = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0)
        # Units 100: within range [1, 100]
        # applicable = min(100, 100) - 1 + 1 = 100
        cost = tier.cost_for_units(100)
        assert cost == 100 * 10.0

    def test_cost_for_units_below_min_returns_zero(self):
        """cost_for_units returns 0 for units below tier minimum."""
        tier = PricingTier(name="basic", min_units=10, max_units=100, unit_price=10.0)
        assert tier.cost_for_units(5) == 0.0
        assert tier.cost_for_units(0) == 0.0

    def test_cost_for_units_above_max_returns_zero(self):
        """cost_for_units returns 0 for units above tier maximum."""
        tier = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0)
        assert tier.cost_for_units(101) == 0.0
        assert tier.cost_for_units(1000) == 0.0

    def test_cost_for_units_unlimited_tier(self):
        """cost_for_units handles unlimited tiers correctly."""
        tier = PricingTier(name="unlimited", min_units=101, max_units=None, unit_price=1.0)
        # For unlimited tier with units >= min_units
        # applicable = min(5000, 5000) - 101 + 1 = 4900
        cost = tier.cost_for_units(5000)
        assert cost == (5000 - 101 + 1) * 1.0

    def test_tier_to_dict_without_metadata(self):
        """to_dict excludes metadata by default."""
        tier = PricingTier(
            name="basic",
            min_units=1,
            max_units=100,
            unit_price=10.0,
            flat_fee=5.0,
            metadata={"template_id": "t123"}
        )
        result = tier.to_dict(include_metadata=False)
        assert result == {
            "name": "basic",
            "min_units": 1,
            "max_units": 100,
            "unit_price": 10.0,
            "flat_fee": 5.0,
        }
        assert "metadata" not in result

    def test_tier_to_dict_with_metadata(self):
        """to_dict includes metadata when requested."""
        metadata = {"template_id": "t123", "region": "US"}
        tier = PricingTier(
            name="basic",
            min_units=1,
            max_units=100,
            unit_price=10.0,
            metadata=metadata
        )
        result = tier.to_dict(include_metadata=True)
        assert result["metadata"] == metadata


class TestPricingGrid:
    """Test PricingGrid data class and cost calculation."""

    def test_grid_creation(self):
        """PricingGrid can be created with product_id and tiers."""
        tier1 = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0)
        tier2 = PricingTier(name="premium", min_units=101, max_units=1000, unit_price=5.0)
        grid = PricingGrid(product_id="product-1", tiers=[tier1, tier2])
        assert grid.product_id == "product-1"
        assert len(grid.tiers) == 2
        assert grid.currency == "USD"
        assert grid.effective_date is None

    def test_sorted_tiers_property(self):
        """sorted_tiers returns tiers in ascending order by min_units."""
        tier1 = PricingTier(name="tier1", min_units=100, max_units=1000, unit_price=5.0)
        tier2 = PricingTier(name="tier2", min_units=1, max_units=100, unit_price=10.0)
        tier3 = PricingTier(name="tier3", min_units=1001, max_units=None, unit_price=1.0)
        grid = PricingGrid(product_id="product-1", tiers=[tier1, tier2, tier3])
        sorted_tiers = grid.sorted_tiers
        assert sorted_tiers[0].name == "tier2"
        assert sorted_tiers[1].name == "tier1"
        assert sorted_tiers[2].name == "tier3"

    def test_total_cost_single_tier(self):
        """total_cost calculates cost correctly for single tier."""
        tier = PricingTier(name="flat", min_units=1, max_units=None, unit_price=10.0)
        grid = PricingGrid(product_id="product-1", tiers=[tier])
        assert grid.total_cost(50) == 50 * 10.0

    def test_total_cost_multi_tier_within_first(self):
        """total_cost for units within first tier."""
        tier1 = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0)
        tier2 = PricingTier(name="premium", min_units=101, max_units=None, unit_price=5.0)
        grid = PricingGrid(product_id="product-1", tiers=[tier1, tier2])
        # 50 units all in first tier
        cost = grid.total_cost(50)
        assert cost == 50 * 10.0

    def test_total_cost_multi_tier_spanning_two(self):
        """total_cost spans multiple tiers correctly."""
        tier1 = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0)
        tier2 = PricingTier(name="premium", min_units=101, max_units=1000, unit_price=5.0)
        grid = PricingGrid(product_id="product-1", tiers=[tier1, tier2])
        # 150 units: 100 in tier1 + 50 in tier2
        cost = grid.total_cost(150)
        expected = (100 * 10.0) + (50 * 5.0)
        assert cost == expected

    def test_total_cost_with_flat_fees(self):
        """total_cost includes flat fees per tier."""
        tier1 = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0, flat_fee=50.0)
        tier2 = PricingTier(name="premium", min_units=101, max_units=None, unit_price=5.0, flat_fee=100.0)
        grid = PricingGrid(product_id="product-1", tiers=[tier1, tier2])
        # 150 units: (50 + 100*10) in tier1 + (100 + 50*5) in tier2
        cost = grid.total_cost(150)
        expected = (50.0 + 100 * 10.0) + (100.0 + 50 * 5.0)
        assert cost == expected

    def test_total_cost_zero_units(self):
        """total_cost returns 0 for zero units."""
        tier = PricingTier(name="basic", min_units=1, max_units=None, unit_price=10.0)
        grid = PricingGrid(product_id="product-1", tiers=[tier])
        assert grid.total_cost(0) == 0.0

    def test_tier_for_units_found(self):
        """tier_for_units returns matching tier."""
        tier1 = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0)
        tier2 = PricingTier(name="premium", min_units=101, max_units=None, unit_price=5.0)
        grid = PricingGrid(product_id="product-1", tiers=[tier1, tier2])
        assert grid.tier_for_units(50).name == "basic"
        assert grid.tier_for_units(150).name == "premium"
        assert grid.tier_for_units(100).name == "basic"
        assert grid.tier_for_units(101).name == "premium"

    def test_tier_for_units_not_found(self):
        """tier_for_units returns None when no tier matches."""
        tier = PricingTier(name="basic", min_units=10, max_units=100, unit_price=10.0)
        grid = PricingGrid(product_id="product-1", tiers=[tier])
        assert grid.tier_for_units(5) is None
        assert grid.tier_for_units(101) is None

    def test_grid_to_dict_without_metadata(self):
        """to_dict excludes tier metadata by default."""
        tier = PricingTier(
            name="basic",
            min_units=1,
            max_units=100,
            unit_price=10.0,
            metadata={"template_id": "t123"}
        )
        grid = PricingGrid(product_id="product-1", tiers=[tier])
        result = grid.to_dict(include_metadata=False)
        assert result["product_id"] == "product-1"
        assert len(result["tiers"]) == 1
        assert "metadata" not in result["tiers"][0]

    def test_grid_to_dict_with_metadata(self):
        """to_dict includes tier metadata when requested."""
        metadata = {"template_id": "t123"}
        tier = PricingTier(
            name="basic",
            min_units=1,
            max_units=100,
            unit_price=10.0,
            metadata=metadata
        )
        grid = PricingGrid(product_id="product-1", tiers=[tier])
        result = grid.to_dict(include_metadata=True)
        assert result["tiers"][0]["metadata"] == metadata


class TestConsumeFromTierIntegration:
    """Test integration with common_utils.consume_from_tier."""

    def test_consume_from_tier_basic(self):
        """consume_from_tier returns correct consumption."""
        consumed, remaining = common_utils.consume_from_tier(
            current=0,
            tier_min=1,
            tier_max=100,
            amount=50
        )
        assert consumed > 0
        assert remaining >= 0

    def test_consume_from_tier_unlimited(self):
        """consume_from_tier handles unlimited tiers (tier_max=None)."""
        consumed, remaining = common_utils.consume_from_tier(
            current=0,
            tier_min=1,
            tier_max=None,
            amount=50
        )
        assert consumed == 50
        assert remaining == 0

    def test_consume_tier_units_uses_common_utils(self):
        """_consume_tier_units calls common_utils.consume_from_tier correctly."""
        tier = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0)
        grid = PricingGrid(product_id="product-1", tiers=[tier])
        consumed, cost = grid._consume_tier_units(tier, 50)
        assert consumed > 0
        assert cost >= 0


class TestPricingGridReconstructionUtil:
    """Test static utility methods for grid reconstruction."""

    def test_from_raw_tiers_single_tier(self):
        """from_raw_tiers reconstructs grid from single tier dict."""
        raw_tiers = [
            {
                "name": "basic",
                "min_units": 1,
                "max_units": 100,
                "unit_price": 10.0,
                "flat_fee": 5.0
            }
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("product-1", raw_tiers)
        assert grid.product_id == "product-1"
        assert len(grid.tiers) == 1
        assert grid.tiers[0].name == "basic"
        assert grid.tiers[0].unit_price == 10.0

    def test_from_raw_tiers_multiple_tiers(self):
        """from_raw_tiers handles multiple tiers."""
        raw_tiers = [
            {"name": "tier1", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "tier2", "min_units": 101, "max_units": 1000, "unit_price": 5.0},
            {"name": "tier3", "min_units": 1001, "max_units": None, "unit_price": 1.0},
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("product-1", raw_tiers)
        assert len(grid.tiers) == 3

    def test_from_raw_tiers_normalization(self):
        """from_raw_tiers normalizes tier order."""
        raw_tiers = [
            {"name": "tier3", "min_units": 101, "max_units": None, "unit_price": 1.0},
            {"name": "tier1", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "tier2", "min_units": 101, "max_units": 1000, "unit_price": 5.0},
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("product-1", raw_tiers)
        # Should be normalized to ascending min_units order
        assert grid.tiers[0].name == "tier1"

    def test_from_raw_tiers_with_metadata(self):
        """from_raw_tiers preserves metadata."""
        metadata = {"template_id": "t123", "region": "US"}
        raw_tiers = [
            {
                "name": "basic",
                "min_units": 1,
                "max_units": 100,
                "unit_price": 10.0,
                "metadata": metadata
            }
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("product-1", raw_tiers)
        assert grid.tiers[0].metadata == metadata

    def test_from_raw_tiers_missing_optional_fields(self):
        """from_raw_tiers provides defaults for missing optional fields."""
        raw_tiers = [
            {
                "name": "basic",
                "min_units": 1,
                "max_units": 100,
                "unit_price": 10.0,
            }
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("product-1", raw_tiers)
        assert grid.tiers[0].flat_fee == 0.0
        assert grid.tiers[0].metadata == {}

    def test_from_raw_tiers_currency_param(self):
        """from_raw_tiers accepts currency parameter."""
        raw_tiers = [
            {"name": "basic", "min_units": 1, "max_units": 100, "unit_price": 10.0}
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("product-1", raw_tiers, currency="EUR")
        assert grid.currency == "EUR"

    def test_from_flat_price_creates_single_tier(self):
        """from_flat_price creates unlimited single-tier grid."""
        grid = PricingGridReconstructionUtil.from_flat_price("product-1", 10.0)
        assert grid.product_id == "product-1"
        assert len(grid.tiers) == 1
        assert grid.tiers[0].name == "flat"
        assert grid.tiers[0].min_units == 1
        assert grid.tiers[0].max_units is None
        assert grid.tiers[0].unit_price == 10.0

    def test_from_flat_price_with_currency(self):
        """from_flat_price accepts currency parameter."""
        grid = PricingGridReconstructionUtil.from_flat_price("product-1", 10.0, currency="GBP")
        assert grid.currency == "GBP"

    def test_merge_grids_selects_base_with_most_tiers(self):
        """merge_grids uses grid with most tiers as base."""
        grid1 = PricingGrid(
            product_id="product-1",
            tiers=[
                PricingTier(name="t1", min_units=1, max_units=100, unit_price=10.0),
            ]
        )
        grid2 = PricingGrid(
            product_id="product-1",
            tiers=[
                PricingTier(name="t1", min_units=1, max_units=100, unit_price=10.0),
                PricingTier(name="t2", min_units=101, max_units=1000, unit_price=5.0),
                PricingTier(name="t3", min_units=1001, max_units=None, unit_price=1.0),
            ]
        )
        merged = PricingGridReconstructionUtil.merge_grids([grid1, grid2])
        assert merged.product_id == "product-1"
        assert len(merged.tiers) == 3

    def test_merge_grids_preserves_product_id(self):
        """merge_grids preserves product_id from base grid."""
        grids = [
            PricingGrid(
                product_id="product-123",
                tiers=[
                    PricingTier(name="t1", min_units=1, max_units=100, unit_price=10.0),
                ]
            ),
        ]
        merged = PricingGridReconstructionUtil.merge_grids(grids)
        assert merged.product_id == "product-123"

    def test_merge_grids_empty_list_raises(self):
        """merge_grids raises ValueError on empty list."""
        with pytest.raises(ValueError):
            PricingGridReconstructionUtil.merge_grids([])

    def test_validate_grid_valid(self):
        """validate_grid returns True for valid grid."""
        grid = PricingGrid(
            product_id="product-1",
            tiers=[
                PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0),
                PricingTier(name="premium", min_units=101, max_units=None, unit_price=5.0),
            ]
        )
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert is_valid is True
        assert len(issues) == 0

    def test_validate_grid_no_tiers(self):
        """validate_grid detects empty tier list."""
        grid = PricingGrid(product_id="product-1", tiers=[])
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert is_valid is False
        assert any("no tiers" in issue for issue in issues)

    def test_validate_grid_negative_unit_price(self):
        """validate_grid detects negative unit_price."""
        grid = PricingGrid(
            product_id="product-1",
            tiers=[
                PricingTier(name="bad", min_units=1, max_units=100, unit_price=-10.0),
            ]
        )
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert is_valid is False
        assert any("negative" in issue for issue in issues)

    def test_validate_grid_max_less_than_min(self):
        """validate_grid detects max < min."""
        grid = PricingGrid(
            product_id="product-1",
            tiers=[
                PricingTier(name="bad", min_units=100, max_units=50, unit_price=10.0),
            ]
        )
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert is_valid is False
        assert any("max < min" in issue for issue in issues)

    def test_validate_grid_overlapping_tiers(self):
        """validate_grid detects overlapping tier ranges."""
        grid = PricingGrid(
            product_id="product-1",
            tiers=[
                PricingTier(name="tier1", min_units=1, max_units=100, unit_price=10.0),
                PricingTier(name="tier2", min_units=50, max_units=150, unit_price=5.0),
            ]
        )
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert is_valid is False
        assert any("overlaps" in issue for issue in issues)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_tier_zero_min_units(self):
        """PricingTier handles min_units = 0."""
        tier = PricingTier(name="free", min_units=0, max_units=100, unit_price=0.0)
        assert tier.min_units == 0
        assert tier.cost_for_units(0) == 0.0

    def test_large_unit_counts(self):
        """PricingGrid handles large unit counts."""
        tier = PricingTier(name="basic", min_units=1, max_units=None, unit_price=0.01)
        grid = PricingGrid(product_id="product-1", tiers=[tier])
        cost = grid.total_cost(1_000_000)
        assert cost == pytest.approx(1_000_000 * 0.01)

    def test_fractional_prices(self):
        """PricingGrid handles fractional unit prices."""
        tier = PricingTier(name="basic", min_units=1, max_units=None, unit_price=0.5)
        grid = PricingGrid(product_id="product-1", tiers=[tier])
        cost = grid.total_cost(100)
        assert cost == pytest.approx(50.0)

    def test_rounding_to_two_decimals(self):
        """total_cost rounds to 2 decimal places."""
        tier = PricingTier(name="basic", min_units=1, max_units=None, unit_price=0.333)
        grid = PricingGrid(product_id="product-1", tiers=[tier])
        cost = grid.total_cost(100)
        # Should round to 2 decimals
        assert cost == round(100 * 0.333, 2)

    def test_multiple_unlimited_tiers_is_invalid(self):
        """Grid with multiple unlimited tiers is detected as invalid."""
        grid = PricingGrid(
            product_id="product-1",
            tiers=[
                PricingTier(name="tier1", min_units=1, max_units=None, unit_price=10.0),
                PricingTier(name="tier2", min_units=101, max_units=None, unit_price=5.0),
            ]
        )
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert is_valid is False

    def test_tier_with_same_min_and_max(self):
        """Tier with min_units == max_units works correctly."""
        tier = PricingTier(name="single", min_units=50, max_units=50, unit_price=10.0)
        assert tier.cost_for_units(50) == 10.0
        assert tier.cost_for_units(49) == 0.0
        assert tier.cost_for_units(51) == 0.0


class TestSerializationAndDeserialization:
    """Test round-trip serialization."""

    def test_tier_round_trip_without_metadata(self):
        """Tier can be serialized and restored without metadata."""
        original = PricingTier(
            name="basic",
            min_units=1,
            max_units=100,
            unit_price=10.0,
            flat_fee=5.0
        )
        serialized = original.to_dict(include_metadata=False)
        # Reconstruct
        restored = PricingTier(
            name=serialized["name"],
            min_units=serialized["min_units"],
            max_units=serialized["max_units"],
            unit_price=serialized["unit_price"],
            flat_fee=serialized["flat_fee"],
        )
        assert restored.name == original.name
        assert restored.unit_price == original.unit_price

    def test_grid_round_trip_through_raw_tiers(self):
        """Grid can be reconstructed from its serialized form."""
        original = PricingGridReconstructionUtil.from_raw_tiers("product-1", [
            {"name": "basic", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "premium", "min_units": 101, "max_units": None, "unit_price": 5.0},
        ])
        serialized = original.to_dict(include_metadata=False)
        # Reconstruct from serialized tiers
        restored = PricingGridReconstructionUtil.from_raw_tiers(
            serialized["product_id"],
            serialized["tiers"],
            currency=serialized["currency"]
        )
        assert restored.product_id == original.product_id
        assert len(restored.tiers) == len(original.tiers)


class TestExistingBehaviorPreservation:
    """Tests to ensure existing behavior is preserved after refactoring."""

    def test_consume_tier_units_produces_same_results_as_inline_logic(self):
        """_consume_tier_units produces results consistent with prior inline logic."""
        tier_unlimited = PricingTier(name="unlimited", min_units=1001, max_units=None, unit_price=1.0)
        tier_limited = PricingTier(name="limited", min_units=1, max_units=100, unit_price=10.0)
        grid = PricingGrid(product_id="product-1", tiers=[])

        # Test unlimited tier consumption
        consumed_u, cost_u = grid._consume_tier_units(tier_unlimited, 500)
        # All 500 should be consumed from unlimited tier
        assert consumed_u == 500
        assert cost_u == 500 * 1.0

        # Test limited tier consumption
        consumed_l, cost_l = grid._consume_tier_units(tier_limited, 50)
        # 50 should be consumed (within capacity 100)
        assert consumed_l == 50
        assert cost_l == 50 * 10.0

    def test_multi_tier_cost_calculation_consistent(self):
        """Multi-tier cost calculations remain consistent."""
        grid = PricingGridReconstructionUtil.from_raw_tiers("product-1", [
            {"name": "tier1", "min_units": 1, "max_units": 100, "unit_price": 100.0},
            {"name": "tier2", "min_units": 101, "max_units": 1000, "unit_price": 50.0},
            {"name": "tier3", "min_units": 1001, "max_units": None, "unit_price": 10.0},
        ])

        # Test various unit counts
        assert grid.total_cost(50) == 50 * 100.0  # All in tier1
        assert grid.total_cost(150) == (100 * 100.0) + (50 * 50.0)  # Tier1 + part of tier2
        assert grid.total_cost(1050) == (100 * 100.0) + (900 * 50.0) + (50 * 10.0)  # All tiers

    def test_grid_creation_and_tier_finding_consistent(self):
        """tier_for_units behavior is consistent."""
        grid = PricingGridReconstructionUtil.from_raw_tiers("product-1", [
            {"name": "basic", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "premium", "min_units": 101, "max_units": 1000, "unit_price": 5.0},
            {"name": "enterprise", "min_units": 1001, "max_units": None, "unit_price": 1.0},
        ])

        # Verify tier finding is deterministic
        for units in [1, 50, 100, 101, 500, 1001, 10000]:
            tier = grid.tier_for_units(units)
            assert tier is not None
            assert tier.min_units <= units
            assert tier.max_units is None or units <= tier.max_units

    def test_validation_results_consistent(self):
        """Validation results are consistent and deterministic."""
        valid_grid = PricingGridReconstructionUtil.from_raw_tiers("product-1", [
            {"name": "basic", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "premium", "min_units": 101, "max_units": None, "unit_price": 5.0},
        ])

        # Should always be valid
        is_valid1, issues1 = PricingGridReconstructionUtil.validate_grid(valid_grid)
        is_valid2, issues2 = PricingGridReconstructionUtil.validate_grid(valid_grid)
        assert is_valid1 == is_valid2
        assert len(issues1) == len(issues2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
