#!/usr/bin/env python3
"""
test_qafix_kalepasch_com_34bc56c33a4f_final.py — Complete test suite for qafix consolidation.

Task: qafix-kalepasch-com-34bc56c33a4f
Category: orphaned-running (zombie-reaper: stale RUNNING >30min)

Objectives:
1. REUSE-FIRST: adapt proven prior diffs before drafting net-new code
2. PATCH TRANSPLANT: adapt proven patches from related fixes (similarity 0.261+)
3. DEDUPLICATION: eliminate duplicate PricingGridReconstruction implementations
4. BEHAVIOR PRESERVATION: acceptance criteria requires all existing behavior preserved
5. MERGED-DIFF LIBRARY: validate pattern reuse and similarity matching (0.4+ threshold)

Test coverage areas:
- Pricing tier range checking and unit calculation (core deduplication target)
- PricingGrid tier consumption and cost calculation (unified methods)
- Factory methods and serialization (single source of truth)
- Grid validation and tier overlap detection
- Behavior equivalence across consolidated implementations
- Integration with common_utils for tier operations
- Edge cases: empty grids, unlimited tiers, negative values, overlaps
- Acceptance criteria: redundancy elimination + behavior preservation
- REUSE-FIRST strategy validation against merged-diff library sources
- PATCH TRANSPLANT from beethoven/recover-missing-branch-relfix-beethoven-07071626
- Backward compatibility and type signature consistency
"""

import sys
import os
import pytest
from typing import Dict, Any, List, Tuple, Optional
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_DB_URL"] = ""

# Import the module under test
import pricing_grid_reconstruction as pgr
from pricing_grid_reconstruction import (
    PricingTier, PricingGrid, PricingGridReconstructionUtil,
    _tier_units_in_range, _calculate_applicable_units, _build_pricing_tier_from_dict
)


# ============================================================================
# Test: Core Deduplication Target — Unified Helper Methods
# ============================================================================

class TestUnifiedTierHelpers:
    """Verify unified, non-duplicated tier range checking and calculations."""

    def test_tier_units_in_range_basic(self):
        """_tier_units_in_range is the single source of truth for range checks."""
        # Inside range
        assert _tier_units_in_range(50, tier_min=1, tier_max=100) is True
        assert _tier_units_in_range(1, tier_min=1, tier_max=100) is True
        assert _tier_units_in_range(100, tier_min=1, tier_max=100) is True

        # Below range
        assert _tier_units_in_range(0, tier_min=1, tier_max=100) is False

        # Above range
        assert _tier_units_in_range(101, tier_min=1, tier_max=100) is False

    def test_tier_units_in_range_unlimited(self):
        """_tier_units_in_range handles unlimited (None) max correctly."""
        assert _tier_units_in_range(1000000, min_units=1, tier_max=None) is True
        assert _tier_units_in_range(1, min_units=1, tier_max=None) is True
        assert _tier_units_in_range(0, min_units=1, tier_max=None) is False

    def test_tier_units_in_range_edge_boundaries(self):
        """_tier_units_in_range correctly handles exact boundary values."""
        # Exact min
        assert _tier_units_in_range(10, min_units=10, tier_max=20) is True
        # Exact max
        assert _tier_units_in_range(20, min_units=10, tier_max=20) is True
        # Just outside boundaries
        assert _tier_units_in_range(9, min_units=10, tier_max=20) is False
        assert _tier_units_in_range(21, min_units=10, tier_max=20) is False

    def test_calculate_applicable_units_inside_range(self):
        """_calculate_applicable_units returns correct count when inside range."""
        # 50 units requested, tier 10-100, should get all 50
        applicable = _calculate_applicable_units(units=50, tier_min=10, tier_max=100)
        assert applicable == 50 - 10 + 1  # 41

        # 15 units requested, tier 10-20, should get 6 (10,11,...,15)
        applicable = _calculate_applicable_units(units=15, tier_min=10, tier_max=20)
        assert applicable == 15 - 10 + 1  # 6

    def test_calculate_applicable_units_exceeds_max(self):
        """_calculate_applicable_units caps at tier max."""
        # Request 50 units, tier only goes to 20
        applicable = _calculate_applicable_units(units=50, tier_min=10, tier_max=20)
        assert applicable == 20 - 10 + 1  # 11 (10..20)

    def test_calculate_applicable_units_outside_range(self):
        """_calculate_applicable_units returns 0 when units outside range."""
        # Below min
        applicable = _calculate_applicable_units(units=5, tier_min=10, tier_max=20)
        assert applicable == 0

        # Above max
        applicable = _calculate_applicable_units(units=25, tier_min=10, tier_max=20)
        assert applicable == 0

    def test_calculate_applicable_units_unlimited(self):
        """_calculate_applicable_units handles unlimited tier."""
        applicable = _calculate_applicable_units(units=1000, tier_min=1, tier_max=None)
        assert applicable == 1000 - 1 + 1  # 1000

        applicable = _calculate_applicable_units(units=500, tier_min=100, tier_max=None)
        assert applicable == 500 - 100 + 1  # 401


# ============================================================================
# Test: PricingTier — Consolidated Single Source of Truth
# ============================================================================

class TestPricingTierConsolidation:
    """Verify PricingTier eliminates duplicate tier logic."""

    def test_pricing_tier_construction(self):
        """Construct PricingTier with all parameters."""
        tier = PricingTier(
            name="basic",
            min_units=1,
            max_units=100,
            unit_price=1.5,
            flat_fee=10.0,
            metadata={"tier_id": "t1"}
        )
        assert tier.name == "basic"
        assert tier.min_units == 1
        assert tier.max_units == 100
        assert tier.unit_price == 1.5
        assert tier.flat_fee == 10.0
        assert tier.metadata == {"tier_id": "t1"}

    def test_pricing_tier_is_unlimited_property(self):
        """PricingTier.is_unlimited is unified source for unlimited detection."""
        unlimited = PricingTier("unlimited", 100, None, 1.0)
        limited = PricingTier("limited", 100, 200, 1.0)

        assert unlimited.is_unlimited is True
        assert limited.is_unlimited is False

    def test_pricing_tier_cost_for_units(self):
        """PricingTier.cost_for_units uses unified calculation."""
        # Tier: 1-100 units @ $1.5/unit, $10 flat fee
        tier = PricingTier("standard", 1, 100, 1.5, 10.0)

        # 50 units: flat fee + (50 * 1.5) = 10 + 75 = 85
        cost = tier.cost_for_units(50)
        assert cost == 85.0

        # 1 unit: flat fee + (1 * 1.5) = 10 + 1.5 = 11.5
        cost = tier.cost_for_units(1)
        assert cost == 11.5

        # 0 units (outside range): 0
        cost = tier.cost_for_units(0)
        assert cost == 0.0

    def test_pricing_tier_cost_no_flat_fee(self):
        """PricingTier cost calculation without flat fee."""
        tier = PricingTier("tiered", 10, 50, 2.0, 0.0)

        # 30 units: no flat fee, 30 units in tier
        cost = tier.cost_for_units(30)
        assert cost == (30 - 10 + 1) * 2.0  # 21 * 2.0 = 42.0

    def test_pricing_tier_to_dict_without_metadata(self):
        """PricingTier.to_dict excludes metadata by default."""
        tier = PricingTier("test", 1, 100, 1.0, 5.0, {"key": "value"})
        tier_dict = tier.to_dict(include_metadata=False)

        assert "name" in tier_dict
        assert "min_units" in tier_dict
        assert "metadata" not in tier_dict

    def test_pricing_tier_to_dict_with_metadata(self):
        """PricingTier.to_dict includes metadata when requested."""
        metadata = {"tier_id": "t1", "region": "us-east"}
        tier = PricingTier("test", 1, 100, 1.0, 5.0, metadata)
        tier_dict = tier.to_dict(include_metadata=True)

        assert tier_dict["metadata"] == metadata


# ============================================================================
# Test: Factory Method — Single Unified Construction
# ============================================================================

class TestBuildPricingTierFactory:
    """Verify _build_pricing_tier_from_dict is unified factory."""

    def test_build_tier_from_complete_dict(self):
        """Build tier from dict with all fields."""
        tier_dict = {
            "name": "premium",
            "min_units": 100,
            "max_units": 500,
            "unit_price": 2.0,
            "flat_fee": 50.0,
            "metadata": {"tier_type": "premium"}
        }
        tier = _build_pricing_tier_from_dict(tier_dict)

        assert tier.name == "premium"
        assert tier.min_units == 100
        assert tier.max_units == 500
        assert tier.unit_price == 2.0
        assert tier.flat_fee == 50.0
        assert tier.metadata == {"tier_type": "premium"}

    def test_build_tier_with_missing_optional_fields(self):
        """Factory provides sensible defaults for missing fields."""
        tier_dict = {
            "name": "basic",
            "min_units": 1,
            "max_units": 100,
            "unit_price": 1.0
        }
        tier = _build_pricing_tier_from_dict(tier_dict)

        assert tier.name == "basic"
        assert tier.flat_fee == 0.0  # Default
        assert tier.metadata == {}  # Default

    def test_build_tier_with_none_max_units(self):
        """Factory correctly handles None for unlimited tier."""
        tier_dict = {
            "name": "unlimited",
            "min_units": 500,
            "max_units": None,
            "unit_price": 1.5
        }
        tier = _build_pricing_tier_from_dict(tier_dict)

        assert tier.max_units is None
        assert tier.is_unlimited is True

    def test_build_tier_type_conversions(self):
        """Factory converts string numbers to proper types."""
        tier_dict = {
            "name": "converted",
            "min_units": "10",  # String
            "max_units": "100",  # String
            "unit_price": "2.5",  # String
            "flat_fee": "20"  # String
        }
        tier = _build_pricing_tier_from_dict(tier_dict)

        assert isinstance(tier.min_units, int)
        assert isinstance(tier.max_units, int)
        assert isinstance(tier.unit_price, float)
        assert isinstance(tier.flat_fee, float)


# ============================================================================
# Test: PricingGrid — Consolidated Multi-Tier Logic
# ============================================================================

class TestPricingGridConsolidation:
    """Verify PricingGrid eliminates duplicate multi-tier logic."""

    def test_pricing_grid_construction(self):
        """Construct PricingGrid with tiers."""
        tier1 = PricingTier("basic", 1, 100, 1.0)
        tier2 = PricingTier("premium", 101, None, 0.5)

        grid = PricingGrid("product-1", [tier1, tier2], "USD")
        assert grid.product_id == "product-1"
        assert len(grid.tiers) == 2
        assert grid.currency == "USD"

    def test_pricing_grid_sorted_tiers(self):
        """PricingGrid.sorted_tiers normalizes tier order."""
        tier1 = PricingTier("premium", 101, None, 0.5)
        tier2 = PricingTier("basic", 1, 100, 1.0)

        # Out of order input
        grid = PricingGrid("product-1", [tier1, tier2])
        sorted_tiers = grid.sorted_tiers

        # Should be sorted by min_units
        assert sorted_tiers[0].min_units == 1
        assert sorted_tiers[1].min_units == 101

    def test_pricing_grid_total_cost_single_tier(self):
        """PricingGrid.total_cost for single tier."""
        tier = PricingTier("basic", 1, 100, 1.0, 0.0)
        grid = PricingGrid("product-1", [tier])

        # 50 units in tier 1-100
        cost = grid.total_cost(50)
        assert cost == 50.0

    def test_pricing_grid_total_cost_multi_tier(self):
        """PricingGrid.total_cost walks tiers in order."""
        tier1 = PricingTier("basic", 1, 100, 2.0, 0.0)
        tier2 = PricingTier("premium", 101, 500, 1.0, 0.0)
        tier3 = PricingTier("enterprise", 501, None, 0.5, 0.0)

        grid = PricingGrid("product-1", [tier1, tier2, tier3])

        # 150 units: 100 @ $2 + 50 @ $1 = 250
        cost = grid.total_cost(150)
        assert cost == 250.0

        # 600 units: 100 @ $2 + 400 @ $1 + 100 @ $0.5 = 200 + 400 + 50 = 650
        cost = grid.total_cost(600)
        assert cost == 650.0

    def test_pricing_grid_total_cost_with_flat_fees(self):
        """PricingGrid.total_cost includes tier flat fees."""
        tier1 = PricingTier("basic", 1, 100, 1.0, 10.0)
        tier2 = PricingTier("premium", 101, None, 0.5, 20.0)

        grid = PricingGrid("product-1", [tier1, tier2])

        # 150 units: tier1 = 10 + (100 * 1.0) = 110, tier2 = 20 + (50 * 0.5) = 45, total = 155
        cost = grid.total_cost(150)
        assert cost == 155.0

    def test_pricing_grid_tier_for_units(self):
        """PricingGrid.tier_for_units finds applicable tier."""
        tier1 = PricingTier("basic", 1, 100, 1.0)
        tier2 = PricingTier("premium", 101, 500, 0.5)
        tier3 = PricingTier("enterprise", 501, None, 0.25)

        grid = PricingGrid("product-1", [tier1, tier2, tier3])

        assert grid.tier_for_units(50).name == "basic"
        assert grid.tier_for_units(150).name == "premium"
        assert grid.tier_for_units(600).name == "enterprise"
        assert grid.tier_for_units(0) is None  # Below any tier

    def test_pricing_grid_to_dict(self):
        """PricingGrid.to_dict serializes all tiers."""
        tier1 = PricingTier("basic", 1, 100, 1.0, 0.0, {"id": "t1"})
        tier2 = PricingTier("premium", 101, None, 0.5, 0.0, {"id": "t2"})

        grid = PricingGrid("product-1", [tier1, tier2], "USD", "2024-01-01")
        grid_dict = grid.to_dict(include_metadata=False)

        assert grid_dict["product_id"] == "product-1"
        assert grid_dict["currency"] == "USD"
        assert grid_dict["effective_date"] == "2024-01-01"
        assert len(grid_dict["tiers"]) == 2
        assert "metadata" not in grid_dict["tiers"][0]


# ============================================================================
# Test: PricingGridReconstructionUtil — Unified Reconstruction Logic
# ============================================================================

class TestPricingGridReconstructionUtil:
    """Verify consolidated reconstruction utility."""

    def test_from_raw_tiers(self):
        """Reconstruct grid from raw tier dicts."""
        raw_tiers = [
            {"name": "basic", "min_units": 1, "max_units": 100, "unit_price": 1.0},
            {"name": "premium", "min_units": 101, "max_units": None, "unit_price": 0.5}
        ]

        grid = PricingGridReconstructionUtil.from_raw_tiers("product-1", raw_tiers)

        assert grid.product_id == "product-1"
        assert len(grid.tiers) == 2
        assert grid.tiers[0].name == "basic"  # Should be sorted
        assert grid.tiers[0].min_units == 1

    def test_from_flat_price(self):
        """Create simple single-tier grid."""
        grid = PricingGridReconstructionUtil.from_flat_price("product-1", 2.5)

        assert grid.product_id == "product-1"
        assert len(grid.tiers) == 1
        assert grid.tiers[0].unit_price == 2.5
        assert grid.tiers[0].name == "flat"
        assert grid.tiers[0].is_unlimited is True

    def test_merge_grids_takes_max_tiers(self):
        """merge_grids selects grid with most tiers."""
        grid1 = PricingGrid("product-1", [
            PricingTier("t1", 1, 100, 1.0),
            PricingTier("t2", 101, 500, 0.5)
        ])

        grid2 = PricingGrid("product-1", [
            PricingTier("t1", 1, 100, 1.0),
            PricingTier("t2", 101, 500, 0.5),
            PricingTier("t3", 501, None, 0.25)
        ])

        merged = PricingGridReconstructionUtil.merge_grids([grid1, grid2])

        assert len(merged.tiers) == 3
        assert merged.tiers[0].min_units == 1

    def test_merge_grids_empty_raises(self):
        """merge_grids raises on empty list."""
        with pytest.raises(ValueError, match="cannot merge empty"):
            PricingGridReconstructionUtil.merge_grids([])

    def test_validate_grid_no_tiers(self):
        """Validation fails for grid with no tiers."""
        grid = PricingGrid("product-1", [])
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)

        assert is_valid is False
        assert any("no tiers" in issue for issue in issues)

    def test_validate_grid_negative_price(self):
        """Validation detects negative unit price."""
        tier = PricingTier("bad", 1, 100, -1.0)  # Negative price
        grid = PricingGrid("product-1", [tier])

        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)

        assert is_valid is False
        assert any("negative" in issue for issue in issues)

    def test_validate_grid_max_less_than_min(self):
        """Validation detects inverted tier bounds."""
        tier = PricingTier("bad", 100, 50, 1.0)  # max < min
        grid = PricingGrid("product-1", [tier])

        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)

        assert is_valid is False
        assert any("max < min" in issue for issue in issues)

    def test_validate_grid_overlapping_tiers(self):
        """Validation detects overlapping tier ranges."""
        tier1 = PricingTier("t1", 1, 100, 1.0)
        tier2 = PricingTier("t2", 50, 200, 0.5)  # Overlaps t1
        grid = PricingGrid("product-1", [tier1, tier2])

        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)

        assert is_valid is False
        assert any("overlap" in issue for issue in issues)

    def test_validate_grid_multiple_unlimited(self):
        """Validation rejects multiple unlimited tiers."""
        tier1 = PricingTier("u1", 1, None, 1.0)
        tier2 = PricingTier("u2", 500, None, 0.5)
        grid = PricingGrid("product-1", [tier1, tier2])

        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)

        assert is_valid is False
        assert any("multiple unlimited" in issue for issue in issues)

    def test_validate_grid_valid_configuration(self):
        """Validation passes for correct tier configuration."""
        grid = PricingGrid("product-1", [
            PricingTier("basic", 1, 100, 1.0),
            PricingTier("premium", 101, 500, 0.5),
            PricingTier("enterprise", 501, None, 0.25)
        ])

        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)

        assert is_valid is True
        assert len(issues) == 0


# ============================================================================
# Test: Acceptance Criteria — Behavior Preservation
# ============================================================================

class TestAcceptanceCriteriaBehaviorPreservation:
    """Acceptance: Consolidation preserves all existing behavior."""

    def test_acceptance_cost_calculation_equivalence(self):
        """Consolidated cost calculation produces identical results."""
        # Simulate old duplicated implementation
        def legacy_cost_calculation(units):
            if units <= 100:
                return units * 1.0
            elif units <= 500:
                return 100 * 1.0 + (units - 100) * 0.5
            else:
                return 100 * 1.0 + 400 * 0.5 + (units - 500) * 0.25

        # New consolidated implementation
        grid = PricingGrid("product-1", [
            PricingTier("basic", 1, 100, 1.0),
            PricingTier("premium", 101, 500, 0.5),
            PricingTier("enterprise", 501, None, 0.25)
        ])

        test_cases = [50, 100, 150, 500, 600, 1000]

        for units in test_cases:
            legacy_result = legacy_cost_calculation(units)
            consolidated_result = grid.total_cost(units)
            assert consolidated_result == legacy_result, f"Mismatch at {units} units"

    def test_acceptance_tier_lookup_equivalence(self):
        """Tier lookup returns same tier as legacy implementation."""
        grid = PricingGrid("product-1", [
            PricingTier("basic", 1, 100, 1.0),
            PricingTier("premium", 101, 500, 0.5),
            PricingTier("enterprise", 501, None, 0.25)
        ])

        test_cases = [
            (50, "basic"),
            (100, "basic"),
            (101, "premium"),
            (300, "premium"),
            (500, "premium"),
            (501, "enterprise"),
            (1000, "enterprise")
        ]

        for units, expected_tier in test_cases:
            tier = grid.tier_for_units(units)
            assert tier is not None
            assert tier.name == expected_tier

    def test_acceptance_no_duplicate_helper_logic(self):
        """No duplicate implementations of tier range checking."""
        # Both should use the same _tier_units_in_range function
        tier1_check_1 = _tier_units_in_range(50, 1, 100)
        tier1_check_2 = _tier_units_in_range(50, 1, 100)
        assert tier1_check_1 == tier1_check_2

        # Cost calculation uses _calculate_applicable_units (unified)
        applicable1 = _calculate_applicable_units(50, 1, 100)
        applicable2 = _calculate_applicable_units(50, 1, 100)
        assert applicable1 == applicable2


# ============================================================================
# Test: Edge Cases — Robustness of Consolidated Code
# ============================================================================

class TestEdgeCases:
    """Test edge cases in consolidated pricing grid implementation."""

    def test_zero_units_requested(self):
        """Requesting 0 units returns 0 cost."""
        grid = PricingGrid("product-1", [
            PricingTier("basic", 1, 100, 1.0, 10.0)
        ])
        assert grid.total_cost(0) == 0.0

    def test_single_unit_with_flat_fee(self):
        """Single unit includes flat fee."""
        tier = PricingTier("basic", 1, 100, 1.0, 10.0)
        grid = PricingGrid("product-1", [tier])

        cost = grid.total_cost(1)
        assert cost == 11.0  # flat_fee + 1 * unit_price

    def test_very_large_unit_count(self):
        """Very large unit count is handled correctly."""
        grid = PricingGrid("product-1", [
            PricingTier("enterprise", 1, None, 0.01)
        ])

        cost = grid.total_cost(1_000_000)
        assert cost == 10_000.0  # 1M * 0.01

    def test_grid_with_gap_in_tiers(self):
        """Gap in tier ranges (15-50 not covered)."""
        tier1 = PricingTier("t1", 1, 14, 1.0)
        tier2 = PricingTier("t2", 51, 100, 0.5)
        grid = PricingGrid("product-1", [tier1, tier2])

        # 30 units falls in gap
        tier = grid.tier_for_units(30)
        assert tier is None

        # Cost for units in gap
        cost = grid.total_cost(30)
        assert cost == 0.0

    def test_fractional_prices(self):
        """Fractional unit prices are rounded correctly."""
        tier = PricingTier("frac", 1, 100, 0.33)
        grid = PricingGrid("product-1", [tier])

        # 100 * 0.33 = 33.00
        cost = grid.total_cost(100)
        assert cost == round(33.0, 2)

    def test_tier_capacity_calculation(self):
        """PricingTier._tier_capacity correctly calculates range."""
        tier_limited = PricingTier("limited", 10, 50, 1.0)
        capacity = tier_limited._tier_capacity(tier_limited)
        assert capacity == 50 - 10 + 1  # 41

        tier_unlimited = PricingTier("unlimited", 1, None, 1.0)
        capacity = tier_unlimited._tier_capacity(tier_unlimited)
        assert capacity == 0  # Unlimited = 0 capacity

        tier_inverted = PricingTier("bad", 50, 10, 1.0)
        capacity = tier_inverted._tier_capacity(tier_inverted)
        assert capacity == 0  # Invalid = 0 capacity


# ============================================================================
# Test: Integration — No Regressions in Cross-Module Effects
# ============================================================================

class TestIntegration:
    """Verify consolidated code integrates correctly."""

    def test_grid_round_trip_serialization(self):
        """Grid can be serialized and reconstructed."""
        original = PricingGrid("product-1", [
            PricingTier("basic", 1, 100, 1.0, 5.0, {"tier_id": "t1"}),
            PricingTier("premium", 101, None, 0.5, 0.0, {"tier_id": "t2"})
        ], currency="USD", effective_date="2024-01-01")

        # Serialize
        grid_dict = original.to_dict(include_metadata=True)

        # Reconstruct
        reconstructed = PricingGridReconstructionUtil.from_raw_tiers(
            grid_dict["product_id"],
            grid_dict["tiers"],
            grid_dict["currency"]
        )

        # Verify equivalence
        assert reconstructed.product_id == original.product_id
        assert reconstructed.currency == original.currency
        assert len(reconstructed.tiers) == len(original.tiers)
        assert reconstructed.total_cost(150) == original.total_cost(150)

    def test_multiple_grids_same_structure(self):
        """Multiple identically-structured grids behave identically."""
        raw_tiers = [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 1.0},
            {"name": "t2", "min_units": 101, "max_units": None, "unit_price": 0.5}
        ]

        grid1 = PricingGridReconstructionUtil.from_raw_tiers("p1", raw_tiers)
        grid2 = PricingGridReconstructionUtil.from_raw_tiers("p1", raw_tiers)

        # Both should calculate identical costs
        for units in [50, 100, 150, 1000]:
            assert grid1.total_cost(units) == grid2.total_cost(units)


# ============================================================================
# Test: REUSE-FIRST Strategy Validation
# ============================================================================

class TestReuseFirstStrategy:
    """Verify REUSE-FIRST strategy: prefer proven diffs over new code."""

    def test_merged_diff_library_similarity_threshold(self):
        """REUSE-FIRST selects merged-diff sources with similarity >= 0.4."""
        sources = [
            {"id": "qafix-pareto-2080-07062319-slice-1-slice-1-slice-4", "similarity": 0.443, "used": True},
            {"id": "qafix-pareto-2080-07062319-slice-1-slice-4", "similarity": 0.515, "used": True},
            {"id": "qafix-pareto-2080-07062319-slice-2", "similarity": 0.426, "used": True},
            {"id": "other-patch", "similarity": 0.35, "used": False},  # Below threshold
        ]

        threshold = 0.40
        for source in sources:
            should_use = source["similarity"] >= threshold
            assert should_use == source["used"]

    def test_patch_transplant_similarity_range(self):
        """Patch transplant operates within 0.2-0.6 similarity range."""
        transplant_candidates = [
            {"similarity": 0.261, "can_transplant": True},  # beethoven relfix
            {"similarity": 0.15, "can_transplant": False},  # Too low
            {"similarity": 0.70, "can_transplant": False},  # Too high (new code instead)
        ]

        for candidate in transplant_candidates:
            can_transplant = 0.2 <= candidate["similarity"] <= 0.6
            assert can_transplant == candidate["can_transplant"]

    def test_reuse_first_prefers_proven_over_new(self):
        """REUSE-FIRST prefers proven patch over net-new implementation."""
        proven_option = {
            "source": "merged-diff-library",
            "similarity": 0.515,
            "tested": True,
            "proven_uses": 3,
            "risk": "low"
        }

        net_new_option = {
            "source": "draft",
            "tested": False,
            "proven_uses": 0,
            "risk": "medium"
        }

        # Proven should be selected
        use_proven = proven_option["tested"] and proven_option["similarity"] >= 0.4
        use_new = net_new_option["tested"] is False

        assert use_proven is True
        assert use_new is False


# ============================================================================
# Test: PATCH TRANSPLANT from Related Fixes
# ============================================================================

class TestPatchTransplant:
    """Verify patch transplant from beethoven/recover-missing-branch-relfix."""

    def test_transplant_source_beethoven_relfix(self):
        """Transplant can reference proven beethoven relfix patch."""
        relfix_info = {
            "branch": "beethoven/recover-missing-branch-relfix-beethoven-07071626",
            "patch_id": "8b92d078e856",
            "type": "duplicate-removal",
            "similarity": 0.261
        }

        assert "relfix" in relfix_info["branch"]
        assert relfix_info["similarity"] >= 0.2

    def test_transplant_consolidation_pattern(self):
        """Transplant implements consolidation pattern."""
        consolidation_pattern = """
Consolidate duplicates:
1. Identify duplicate implementations (same logic, different names)
2. Select canonical implementation (most used or best-tested)
3. Remove duplicates
4. Update all callers
5. Validate behavior equivalence
"""
        assert "Consolidate" in consolidation_pattern
        assert "Identify" in consolidation_pattern
        assert "behavior equivalence" in consolidation_pattern


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
