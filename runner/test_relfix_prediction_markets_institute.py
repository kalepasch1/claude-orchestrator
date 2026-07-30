#!/usr/bin/env python3
"""
test_relfix_prediction_markets_institute.py - Tests for relfix-prediction-markets-institute-07290017.

Validates the adapted patch for pricing_grid_reconstruction.py:
  - Helper functions for tier unit calculations
  - Integration with common_utils.consume_from_tier
  - Grid validation for multiple unlimited tiers
  - Preservation of existing behavior with refactored code
  - No design_fingerprint TypeError regressions

Environment variables tested:
  ORCH_DB_ENABLED: false (tests are deterministic)
"""
import sys
import os
import pytest
from typing import Dict, Any, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable DB at module load
os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_DB_URL"] = ""

# Import the module under test
from pricing_grid_reconstruction import (
    PricingTier,
    PricingGrid,
    PricingGridReconstructionUtil,
    _tier_units_in_range,
    _calculate_applicable_units,
    _build_pricing_tier_from_dict,
)
import common_utils


class TestTierUnitsInRange:
    """Test the _tier_units_in_range helper function."""

    def test_units_below_min_returns_false(self):
        """_tier_units_in_range returns False when units < tier_min."""
        assert _tier_units_in_range(5, tier_min=10, tier_max=100) is False

    def test_units_at_min_returns_true(self):
        """_tier_units_in_range returns True when units == tier_min."""
        assert _tier_units_in_range(10, tier_min=10, tier_max=100) is True

    def test_units_within_range_returns_true(self):
        """_tier_units_in_range returns True for units within [min, max]."""
        assert _tier_units_in_range(50, tier_min=10, tier_max=100) is True

    def test_units_at_max_returns_true(self):
        """_tier_units_in_range returns True when units == tier_max."""
        assert _tier_units_in_range(100, tier_min=10, tier_max=100) is True

    def test_units_above_max_returns_false(self):
        """_tier_units_in_range returns False when units > tier_max."""
        assert _tier_units_in_range(101, tier_min=10, tier_max=100) is False

    def test_units_with_unlimited_tier(self):
        """_tier_units_in_range handles unlimited tier (max_units=None)."""
        # With unlimited, only lower bound matters
        assert _tier_units_in_range(1000, tier_min=10, tier_max=None) is True
        assert _tier_units_in_range(5, tier_min=10, tier_max=None) is False

    def test_zero_units_below_min(self):
        """_tier_units_in_range handles zero units."""
        assert _tier_units_in_range(0, tier_min=10, tier_max=100) is False

    def test_single_unit_tier(self):
        """_tier_units_in_range works for single-unit tier (min==max)."""
        assert _tier_units_in_range(50, tier_min=50, tier_max=50) is True
        assert _tier_units_in_range(49, tier_min=50, tier_max=50) is False
        assert _tier_units_in_range(51, tier_min=50, tier_max=50) is False


class TestCalculateApplicableUnits:
    """Test the _calculate_applicable_units helper function."""

    def test_units_below_min_returns_zero(self):
        """_calculate_applicable_units returns 0 when units < tier_min."""
        result = _calculate_applicable_units(5, tier_min=10, tier_max=100)
        assert result == 0

    def test_units_at_min_returns_one(self):
        """_calculate_applicable_units returns 1 when units == tier_min."""
        result = _calculate_applicable_units(10, tier_min=10, tier_max=100)
        assert result == 1

    def test_units_within_range_returns_applicable_count(self):
        """_calculate_applicable_units returns correct count within range."""
        # 50 units in tier [10, 100]: applicable = min(50, 100) - 10 + 1 = 41
        result = _calculate_applicable_units(50, tier_min=10, tier_max=100)
        assert result == 41

    def test_units_at_max_returns_full_tier_capacity(self):
        """_calculate_applicable_units returns tier capacity at max."""
        # 100 units in tier [10, 100]: applicable = min(100, 100) - 10 + 1 = 91
        result = _calculate_applicable_units(100, tier_min=10, tier_max=100)
        assert result == 91

    def test_units_above_max_returns_zero(self):
        """_calculate_applicable_units returns 0 when units > tier_max."""
        # 150 units in tier [10, 100]: outside range, returns 0
        result = _calculate_applicable_units(150, tier_min=10, tier_max=100)
        assert result == 0

    def test_unlimited_tier_uses_units_as_upper(self):
        """_calculate_applicable_units uses units for upper bound in unlimited tier."""
        # 1000 units in unlimited tier [1001, None]: outside range, returns 0
        result = _calculate_applicable_units(1000, tier_min=1001, tier_max=None)
        assert result == 0
        # 5000 units in unlimited tier [1001, None]: applicable = min(5000, 5000) - 1001 + 1
        result = _calculate_applicable_units(5000, tier_min=1001, tier_max=None)
        assert result == 4000

    def test_zero_units_outside_range(self):
        """_calculate_applicable_units returns 0 for zero units outside tier."""
        result = _calculate_applicable_units(0, tier_min=10, tier_max=100)
        assert result == 0

    def test_single_unit_tier(self):
        """_calculate_applicable_units works for single-unit tier."""
        # 50 units in tier [50, 50]: applicable = min(50, 50) - 50 + 1 = 1
        result = _calculate_applicable_units(50, tier_min=50, tier_max=50)
        assert result == 1
        # 49 units in tier [50, 50]: outside, returns 0
        result = _calculate_applicable_units(49, tier_min=50, tier_max=50)
        assert result == 0

    def test_boundary_between_tiers(self):
        """_calculate_applicable_units handles boundaries correctly."""
        # For tier [1, 100] at boundary
        result = _calculate_applicable_units(100, tier_min=1, tier_max=100)
        assert result == 100
        # 101 units in tier [1, 100]: outside range, returns 0
        result = _calculate_applicable_units(101, tier_min=1, tier_max=100)
        assert result == 0


class TestBuildPricingTierFromDict:
    """Test the _build_pricing_tier_from_dict helper function."""

    def test_minimal_tier_dict(self):
        """_build_pricing_tier_from_dict constructs tier from minimal dict."""
        tier_dict = {
            "name": "basic",
            "min_units": 1,
            "max_units": 100,
            "unit_price": 10.0,
        }
        tier = _build_pricing_tier_from_dict(tier_dict)
        assert tier.name == "basic"
        assert tier.min_units == 1
        assert tier.max_units == 100
        assert tier.unit_price == 10.0
        assert tier.flat_fee == 0.0
        assert tier.metadata == {}

    def test_tier_dict_with_flat_fee(self):
        """_build_pricing_tier_from_dict includes flat_fee when present."""
        tier_dict = {
            "name": "premium",
            "min_units": 101,
            "max_units": 1000,
            "unit_price": 5.0,
            "flat_fee": 50.0,
        }
        tier = _build_pricing_tier_from_dict(tier_dict)
        assert tier.flat_fee == 50.0

    def test_tier_dict_with_metadata(self):
        """_build_pricing_tier_from_dict preserves metadata."""
        metadata = {"template_id": "t123", "region": "US"}
        tier_dict = {
            "name": "basic",
            "min_units": 1,
            "max_units": 100,
            "unit_price": 10.0,
            "metadata": metadata,
        }
        tier = _build_pricing_tier_from_dict(tier_dict)
        assert tier.metadata == metadata

    def test_tier_dict_with_unlimited_max(self):
        """_build_pricing_tier_from_dict handles unlimited tier (max_units=None)."""
        tier_dict = {
            "name": "unlimited",
            "min_units": 1001,
            "max_units": None,
            "unit_price": 1.0,
        }
        tier = _build_pricing_tier_from_dict(tier_dict)
        assert tier.max_units is None
        assert tier.is_unlimited is True

    def test_tier_dict_type_conversions(self):
        """_build_pricing_tier_from_dict converts string values to proper types."""
        tier_dict = {
            "name": "basic",
            "min_units": "1",
            "max_units": "100",
            "unit_price": "10.0",
            "flat_fee": "5.0",
        }
        tier = _build_pricing_tier_from_dict(tier_dict)
        assert isinstance(tier.min_units, int)
        assert isinstance(tier.max_units, int)
        assert isinstance(tier.unit_price, float)
        assert isinstance(tier.flat_fee, float)

    def test_tier_dict_missing_optional_fields(self):
        """_build_pricing_tier_from_dict provides defaults for missing fields."""
        tier_dict = {
            "name": "basic",
            "min_units": 1,
            "max_units": 100,
            "unit_price": 10.0,
        }
        tier = _build_pricing_tier_from_dict(tier_dict)
        assert tier.flat_fee == 0.0
        assert tier.metadata == {}

    def test_tier_dict_missing_name_uses_default(self):
        """_build_pricing_tier_from_dict uses 'default' for missing name."""
        tier_dict = {
            "min_units": 1,
            "max_units": 100,
            "unit_price": 10.0,
        }
        tier = _build_pricing_tier_from_dict(tier_dict)
        assert tier.name == "default"

    def test_tier_dict_zero_prices_allowed(self):
        """_build_pricing_tier_from_dict allows zero unit_price."""
        tier_dict = {
            "name": "free",
            "min_units": 1,
            "max_units": 100,
            "unit_price": 0.0,
        }
        tier = _build_pricing_tier_from_dict(tier_dict)
        assert tier.unit_price == 0.0


class TestConsumeFromTierIntegration:
    """Test integration between _consume_tier_units and common_utils.consume_from_tier."""

    def test_consume_tier_units_calls_common_utils(self):
        """_consume_tier_units correctly delegates to common_utils.consume_from_tier."""
        tier = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0)
        grid = PricingGrid(product_id="product-1", tiers=[tier])

        consumed, cost = grid._consume_tier_units(tier, 50)
        # common_utils returns (units_consumed, units_remaining)
        # We verify consumed is > 0 and cost is calculated
        assert consumed > 0
        assert cost == (consumed * 10.0)

    def test_consume_tier_units_with_flat_fee(self):
        """_consume_tier_units includes flat_fee in cost calculation."""
        tier = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0, flat_fee=50.0)
        grid = PricingGrid(product_id="product-1", tiers=[tier])

        consumed, cost = grid._consume_tier_units(tier, 50)
        # Cost should include flat fee + unit costs
        assert cost == (50.0 + (consumed * 10.0))

    def test_consume_tier_units_unlimited_tier(self):
        """_consume_tier_units handles unlimited tier through common_utils."""
        tier = PricingTier(name="unlimited", min_units=101, max_units=None, unit_price=1.0)
        grid = PricingGrid(product_id="product-1", tiers=[tier])

        consumed, cost = grid._consume_tier_units(tier, 500)
        # All 500 should be consumed from unlimited tier
        assert consumed == 500
        assert cost == 500 * 1.0

    def test_consume_tier_units_limited_tier_respects_capacity(self):
        """_consume_tier_units respects tier capacity through common_utils."""
        tier = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0)
        grid = PricingGrid(product_id="product-1", tiers=[tier])

        consumed, cost = grid._consume_tier_units(tier, 200)
        # Should be limited by tier capacity
        assert consumed <= 100
        assert cost == (consumed * 10.0)

    def test_consume_tier_units_zero_remaining(self):
        """_consume_tier_units returns zero when no remaining units."""
        tier = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0)
        grid = PricingGrid(product_id="product-1", tiers=[tier])

        consumed, cost = grid._consume_tier_units(tier, 0)
        assert consumed == 0
        assert cost == 0.0

    def test_consume_tier_units_negative_remaining_returns_zero(self):
        """_consume_tier_units handles negative remaining safely."""
        tier = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0)
        grid = PricingGrid(product_id="product-1", tiers=[tier])

        consumed, cost = grid._consume_tier_units(tier, -10)
        assert consumed == 0
        assert cost == 0.0


class TestMultipleUnlimitedTiersValidation:
    """Test validation for multiple unlimited tiers."""

    def test_validate_grid_detects_multiple_unlimited_tiers(self):
        """validate_grid detects and rejects multiple unlimited tiers."""
        grid = PricingGrid(
            product_id="product-1",
            tiers=[
                PricingTier(name="tier1", min_units=1, max_units=None, unit_price=10.0),
                PricingTier(name="tier2", min_units=101, max_units=None, unit_price=5.0),
            ]
        )
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert is_valid is False
        assert any("multiple unlimited" in issue for issue in issues)

    def test_validate_grid_allows_single_unlimited_tier(self):
        """validate_grid allows single unlimited tier."""
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

    def test_validate_grid_allows_no_unlimited_tiers(self):
        """validate_grid allows grids with no unlimited tiers."""
        grid = PricingGrid(
            product_id="product-1",
            tiers=[
                PricingTier(name="tier1", min_units=1, max_units=100, unit_price=10.0),
                PricingTier(name="tier2", min_units=101, max_units=1000, unit_price=5.0),
            ]
        )
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert is_valid is True
        assert len(issues) == 0

    def test_validate_grid_three_unlimited_tiers_is_invalid(self):
        """validate_grid detects three unlimited tiers as invalid."""
        grid = PricingGrid(
            product_id="product-1",
            tiers=[
                PricingTier(name="tier1", min_units=1, max_units=None, unit_price=10.0),
                PricingTier(name="tier2", min_units=101, max_units=None, unit_price=5.0),
                PricingTier(name="tier3", min_units=201, max_units=None, unit_price=1.0),
            ]
        )
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert is_valid is False
        assert len(issues) == 1
        assert "multiple unlimited" in issues[0]


class TestExistingBehaviorPreservation:
    """Tests to ensure existing behavior is preserved after refactoring."""

    def test_tier_capacity_calculation_preserved(self):
        """_tier_capacity still calculates correctly after refactor."""
        tier_limited = PricingTier(name="limited", min_units=1, max_units=100, unit_price=10.0)
        tier_unlimited = PricingTier(name="unlimited", min_units=101, max_units=None, unit_price=5.0)

        # Limited tier capacity: 100 - 1 + 1 = 100
        assert PricingTier._tier_capacity(tier_limited) == 100
        # Unlimited tier capacity: 0
        assert PricingTier._tier_capacity(tier_unlimited) == 0

    def test_cost_for_units_behavior_preserved(self):
        """cost_for_units behavior unchanged after refactoring."""
        tier = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0, flat_fee=5.0)

        # Cost at 50 units: 5.0 + (50 * 10.0) = 505.0
        assert tier.cost_for_units(50) == 505.0
        # Cost below min: 0
        assert tier.cost_for_units(0) == 0.0
        # Cost above max: 0
        assert tier.cost_for_units(101) == 0.0

    def test_multi_tier_total_cost_preserved(self):
        """Multi-tier total_cost calculation unchanged after refactoring."""
        grid = PricingGrid(
            product_id="product-1",
            tiers=[
                PricingTier(name="tier1", min_units=1, max_units=100, unit_price=100.0),
                PricingTier(name="tier2", min_units=101, max_units=1000, unit_price=50.0),
                PricingTier(name="tier3", min_units=1001, max_units=None, unit_price=10.0),
            ]
        )

        # Test various unit counts to verify consistent calculation
        cost_50 = grid.total_cost(50)
        cost_150 = grid.total_cost(150)
        cost_1050 = grid.total_cost(1050)

        # All should be positive and reasonable
        assert cost_50 > 0
        assert cost_150 > cost_50
        assert cost_1050 > cost_150

    def test_tier_for_units_behavior_preserved(self):
        """tier_for_units behavior unchanged after refactoring."""
        grid = PricingGrid(
            product_id="product-1",
            tiers=[
                PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0),
                PricingTier(name="premium", min_units=101, max_units=1000, unit_price=5.0),
                PricingTier(name="enterprise", min_units=1001, max_units=None, unit_price=1.0),
            ]
        )

        # Each unit count should find its correct tier
        assert grid.tier_for_units(50).name == "basic"
        assert grid.tier_for_units(100).name == "basic"
        assert grid.tier_for_units(101).name == "premium"
        assert grid.tier_for_units(1000).name == "premium"
        assert grid.tier_for_units(1001).name == "enterprise"
        assert grid.tier_for_units(10000).name == "enterprise"

    def test_grid_serialization_preserved(self):
        """Grid serialization behavior unchanged after refactoring."""
        metadata = {"template_id": "t123"}
        grid = PricingGrid(
            product_id="product-1",
            tiers=[
                PricingTier(
                    name="basic",
                    min_units=1,
                    max_units=100,
                    unit_price=10.0,
                    metadata=metadata
                )
            ]
        )

        # Without metadata
        serialized = grid.to_dict(include_metadata=False)
        assert "metadata" not in serialized["tiers"][0]

        # With metadata
        serialized_with_meta = grid.to_dict(include_metadata=True)
        assert serialized_with_meta["tiers"][0]["metadata"] == metadata

    def test_validation_behavior_preserved(self):
        """Grid validation logic unchanged after refactoring."""
        valid_grid = PricingGrid(
            product_id="product-1",
            tiers=[
                PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0),
                PricingTier(name="premium", min_units=101, max_units=None, unit_price=5.0),
            ]
        )

        is_valid, issues = PricingGridReconstructionUtil.validate_grid(valid_grid)
        assert is_valid is True
        assert len(issues) == 0

        # Should be deterministic
        is_valid2, issues2 = PricingGridReconstructionUtil.validate_grid(valid_grid)
        assert is_valid == is_valid2
        assert len(issues) == len(issues2)


class TestRegressionPrevention:
    """Tests to prevent regressions (e.g., design_fingerprint TypeError)."""

    def test_no_design_fingerprint_in_pricing_grid_creation(self):
        """PricingGrid creation does not require design_fingerprint parameter."""
        # Should not raise TypeError about unexpected keyword argument
        grid = PricingGrid(product_id="product-1", tiers=[])
        assert grid.product_id == "product-1"

    def test_from_raw_tiers_no_design_fingerprint_param(self):
        """from_raw_tiers does not require design_fingerprint parameter."""
        # Should not raise TypeError about unexpected keyword argument
        grid = PricingGridReconstructionUtil.from_raw_tiers(
            "product-1",
            [{"name": "tier1", "min_units": 1, "max_units": 100, "unit_price": 10.0}]
        )
        assert grid.product_id == "product-1"

    def test_pricing_tier_creation_no_design_fingerprint(self):
        """PricingTier creation does not require design_fingerprint parameter."""
        # Should not raise TypeError about unexpected keyword argument
        tier = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0)
        assert tier.name == "basic"

    def test_validate_grid_no_design_fingerprint_param(self):
        """validate_grid does not require design_fingerprint parameter."""
        grid = PricingGrid(
            product_id="product-1",
            tiers=[PricingTier(name="tier1", min_units=1, max_units=100, unit_price=10.0)]
        )
        # Should not raise TypeError about unexpected keyword argument
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert isinstance(is_valid, bool)
        assert isinstance(issues, list)

    def test_merge_grids_no_design_fingerprint_param(self):
        """merge_grids does not require design_fingerprint parameter."""
        grids = [
            PricingGrid(
                product_id="product-1",
                tiers=[PricingTier(name="tier1", min_units=1, max_units=100, unit_price=10.0)]
            )
        ]
        # Should not raise TypeError about unexpected keyword argument
        merged = PricingGridReconstructionUtil.merge_grids(grids)
        assert merged.product_id == "product-1"


class TestAdaptedPatchSmallestDiff:
    """Tests to ensure the adapted patch maintains smallest mergeable diff."""

    def test_no_functionality_changed_from_original(self):
        """The refactored code produces identical results to original inline logic."""
        # Create grids using the refactored path
        grid1 = PricingGridReconstructionUtil.from_raw_tiers("product-1", [
            {"name": "tier1", "min_units": 1, "max_units": 100, "unit_price": 100.0},
            {"name": "tier2", "min_units": 101, "max_units": 1000, "unit_price": 50.0},
        ])

        # Verify that _consume_tier_units via common_utils produces correct costs
        tier = grid1.tiers[0]
        consumed, cost = grid1._consume_tier_units(tier, 50)

        # Cost should be 50 * 100.0 = 5000.0
        assert cost == 5000.0

    def test_helper_functions_are_pure(self):
        """Helper functions produce deterministic outputs (pure functions)."""
        # Multiple calls with same input should give same output
        for _ in range(5):
            result1 = _tier_units_in_range(50, tier_min=10, tier_max=100)
            result2 = _tier_units_in_range(50, tier_min=10, tier_max=100)
            assert result1 == result2

            result3 = _calculate_applicable_units(50, tier_min=10, tier_max=100)
            result4 = _calculate_applicable_units(50, tier_min=10, tier_max=100)
            assert result3 == result4

    def test_tier_capacity_calculation_matches_inline_logic(self):
        """_tier_capacity calculation matches previous inline formula."""
        # Test with limited tier: should be max - min + 1
        tier_limited = PricingTier(name="basic", min_units=10, max_units=100, unit_price=10.0)
        capacity = PricingTier._tier_capacity(tier_limited)
        expected = 100 - 10 + 1
        assert capacity == expected

        # Test with unlimited tier: should be 0
        tier_unlimited = PricingTier(name="unlimited", min_units=101, max_units=None, unit_price=1.0)
        capacity = PricingTier._tier_capacity(tier_unlimited)
        assert capacity == 0

    def test_round_trip_serialization_unchanged(self):
        """Serialization and deserialization behavior unchanged."""
        original = PricingGridReconstructionUtil.from_raw_tiers("product-1", [
            {"name": "tier1", "min_units": 1, "max_units": 100, "unit_price": 10.0, "flat_fee": 5.0},
            {"name": "tier2", "min_units": 101, "max_units": None, "unit_price": 5.0},
        ])

        # Serialize
        serialized = original.to_dict(include_metadata=False)

        # Deserialize
        restored = PricingGridReconstructionUtil.from_raw_tiers(
            serialized["product_id"],
            serialized["tiers"],
            currency=serialized["currency"]
        )

        # Verify same behavior
        original_cost = original.total_cost(150)
        restored_cost = restored.total_cost(150)
        assert original_cost == restored_cost


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
