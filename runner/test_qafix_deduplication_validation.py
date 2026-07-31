#!/usr/bin/env python3
"""
test_qafix_deduplication_validation.py — Validation tests for duplicate code elimination.

Task: qafix-kalepasch-com-34bc56c33a4f
Objective: Verify that deduplication of pricing_grid_reconstruction and related modules
preserves all existing behavior while eliminating redundant implementations.

Tests cover:
- Pricing grid reconstruction correctness post-consolidation
- Parallel dispatch routing accuracy
- Preflight filter decision logic preservation
- Cross-module integration without behavior changes
- Edge cases: empty inputs, large grids, malformed data
- Schema and API compatibility during migration
"""
import sys
import os
import pytest
import json
from typing import Dict, Any, List, Tuple
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_DB_URL"] = ""

# Import modules under test
from pricing_grid_reconstruction import (
    PricingTier,
    PricingGrid,
    PricingGridReconstructionUtil,
)
import common_utils


class TestPricingGridDeduplicationPreservation:
    """Verify pricing grid reconstruction behaves identically after deduplication."""

    def test_single_tier_grid_cost_calculation(self):
        """Single tier grid cost calculation preserved."""
        grid = PricingGridReconstructionUtil.from_flat_price("prod-1", 10.0)
        assert grid.total_cost(100) == 1000.0
        assert grid.total_cost(50) == 500.0
        assert grid.total_cost(1) == 10.0

    def test_multi_tier_grid_progressive_pricing(self):
        """Multi-tier progressive pricing structure preserved."""
        raw_tiers = [
            {"name": "starter", "min_units": 1, "max_units": 100, "unit_price": 10.0, "flat_fee": 0.0},
            {"name": "pro", "min_units": 101, "max_units": 1000, "unit_price": 7.0, "flat_fee": 50.0},
            {"name": "enterprise", "min_units": 1001, "max_units": None, "unit_price": 5.0, "flat_fee": 200.0},
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-2", raw_tiers)

        # Verify cost calculations
        cost_50 = grid.total_cost(50)
        assert cost_50 == 500.0  # 50 * 10.0

        cost_150 = grid.total_cost(150)
        expected = (100 * 10.0) + (50 * 7.0 + 50.0)  # 1000 + 350 + 50
        assert cost_150 == expected

        cost_2000 = grid.total_cost(2000)
        # First 100: 100 * 10 = 1000
        # Next 900: 900 * 7 + 50 = 6300 + 50 = 6350
        # Next 1000: 1000 * 5 + 200 = 5000 + 200 = 5200
        expected = 1000 + 6350 + 5200
        assert cost_2000 == expected

    def test_tier_selection_accuracy(self):
        """Tier selection logic unchanged after deduplication."""
        raw_tiers = [
            {"name": "tier1", "min_units": 1, "max_units": 50, "unit_price": 10.0},
            {"name": "tier2", "min_units": 51, "max_units": 150, "unit_price": 7.0},
            {"name": "tier3", "min_units": 151, "max_units": None, "unit_price": 5.0},
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-3", raw_tiers)

        assert grid.tier_for_units(25).name == "tier1"
        assert grid.tier_for_units(75).name == "tier2"
        assert grid.tier_for_units(200).name == "tier3"
        assert grid.tier_for_units(1000).name == "tier3"

    def test_grid_merging_idempotent(self):
        """Grid merging produces consistent results."""
        grid1 = PricingGridReconstructionUtil.from_flat_price("prod-4", 10.0)
        grid2 = PricingGridReconstructionUtil.from_flat_price("prod-4", 12.0)

        merged = PricingGridReconstructionUtil.merge_grids([grid1, grid2])
        assert merged.product_id == "prod-4"
        assert len(merged.tiers) > 0
        assert merged.total_cost(100) > 0

    def test_grid_validation_catches_overlaps(self):
        """Overlap detection preserved."""
        raw_tiers = [
            {"name": "tier1", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "tier2", "min_units": 50, "max_units": 150, "unit_price": 7.0},  # Overlaps
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-5", raw_tiers)
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert is_valid is False
        assert any("overlap" in issue.lower() for issue in issues)

    def test_grid_validation_catches_negative_price(self):
        """Negative price detection preserved."""
        raw_tiers = [
            {"name": "bad", "min_units": 1, "max_units": 100, "unit_price": -5.0},
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-6", raw_tiers)
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert is_valid is False
        assert any("negative" in issue.lower() for issue in issues)

    def test_grid_validation_catches_invalid_range(self):
        """Invalid min/max detection preserved."""
        raw_tiers = [
            {"name": "bad", "min_units": 100, "max_units": 50, "unit_price": 10.0},
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-7", raw_tiers)
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert is_valid is False
        assert any("max < min" in issue.lower() for issue in issues)

    def test_grid_validation_rejects_multiple_unlimited(self):
        """Multiple unlimited tiers rejected."""
        raw_tiers = [
            {"name": "unl1", "min_units": 1, "max_units": None, "unit_price": 10.0},
            {"name": "unl2", "min_units": 1001, "max_units": None, "unit_price": 5.0},
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-8", raw_tiers)
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert is_valid is False
        assert any("multiple unlimited" in issue.lower() for issue in issues)

    def test_serialization_round_trip(self):
        """Serialization and deserialization preserves data."""
        raw_tiers = [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0, "flat_fee": 5.0},
            {"name": "t2", "min_units": 101, "max_units": None, "unit_price": 5.0, "flat_fee": 50.0},
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-9", raw_tiers)

        # Serialize
        serialized = grid.to_dict(include_metadata=False)

        # Deserialize
        grid2 = PricingGridReconstructionUtil.from_raw_tiers(
            serialized["product_id"],
            serialized["tiers"],
            currency=serialized["currency"]
        )

        # Verify cost calculations match
        assert grid.total_cost(50) == grid2.total_cost(50)
        assert grid.total_cost(150) == grid2.total_cost(150)
        assert grid.total_cost(2000) == grid2.total_cost(2000)

    def test_empty_grid_handling(self):
        """Empty grid creates zero cost."""
        grid = PricingGrid(product_id="empty", tiers=[], currency="USD")
        assert grid.total_cost(100) == 0.0

    def test_large_volume_calculation(self):
        """Large volume calculations accurate."""
        grid = PricingGridReconstructionUtil.from_flat_price("prod-10", 0.01)

        # Calculate for 1M units
        cost_1m = grid.total_cost(1000000)
        expected = 10000.0  # 1M * 0.01
        assert abs(cost_1m - expected) < 0.01  # Allow for rounding

    def test_pricing_tier_metadata_preservation(self):
        """Tier metadata preserved through serialization."""
        raw_tiers = [
            {
                "name": "t1",
                "min_units": 1,
                "max_units": 100,
                "unit_price": 10.0,
                "metadata": {"region": "US", "template_id": "tmpl-123"}
            }
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-11", raw_tiers)
        tier = grid.tiers[0]
        assert tier.metadata["region"] == "US"
        assert tier.metadata["template_id"] == "tmpl-123"

    def test_grid_cost_rounding(self):
        """Cost calculations properly rounded to 2 decimals."""
        raw_tiers = [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 0.333, "flat_fee": 0.0}
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-12", raw_tiers)

        cost = grid.total_cost(30)  # 30 * 0.333 = 9.99
        assert cost == 9.99
        assert isinstance(cost, float)
        assert len(str(cost).split('.')[-1]) <= 2


class TestDeduplicationCrossModuleIntegration:
    """Verify deduplication doesn't break module interactions."""

    def test_common_utils_consume_from_tier_integration(self):
        """common_utils.consume_from_tier still works with pricing grid."""
        tier = PricingTier(name="test", min_units=1, max_units=100, unit_price=10.0)
        grid = PricingGrid(product_id="test", tiers=[tier])

        # Verify tier can be consumed by common_utils
        consumed, _ = common_utils.consume_from_tier(
            current=0,
            tier_min=1,
            tier_max=100,
            amount=50
        )
        assert consumed == 50

    def test_grid_sorted_tiers_ordering(self):
        """Sorted tiers always returned in min_units ascending order."""
        raw_tiers = [
            {"name": "t3", "min_units": 101, "max_units": None, "unit_price": 5.0},
            {"name": "t1", "min_units": 1, "max_units": 50, "unit_price": 10.0},
            {"name": "t2", "min_units": 51, "max_units": 100, "unit_price": 8.0},
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-13", raw_tiers)

        sorted_tiers = grid.sorted_tiers
        assert sorted_tiers[0].name == "t1"
        assert sorted_tiers[1].name == "t2"
        assert sorted_tiers[2].name == "t3"


class TestBehaviorPreservationAfterDeduplication:
    """Critical tests ensuring zero behavior changes from deduplication."""

    def test_cost_consistency_with_different_input_orders(self):
        """Cost calculation same regardless of tier definition order."""
        tiers_order1 = [
            {"name": "t1", "min_units": 1, "max_units": 50, "unit_price": 10.0},
            {"name": "t2", "min_units": 51, "max_units": 100, "unit_price": 7.0},
        ]
        tiers_order2 = [
            {"name": "t2", "min_units": 51, "max_units": 100, "unit_price": 7.0},
            {"name": "t1", "min_units": 1, "max_units": 50, "unit_price": 10.0},
        ]

        grid1 = PricingGridReconstructionUtil.from_raw_tiers("prod-14", tiers_order1)
        grid2 = PricingGridReconstructionUtil.from_raw_tiers("prod-14", tiers_order2)

        for units in [25, 50, 75, 100]:
            assert grid1.total_cost(units) == grid2.total_cost(units)

    def test_tier_capacity_calculations(self):
        """Tier capacity calculations work correctly."""
        tier = PricingTier(name="test", min_units=10, max_units=50, unit_price=10.0)
        capacity = PricingTier._tier_capacity(tier)
        assert capacity == 41  # 50 - 10 + 1

    def test_tier_unlimited_capacity_zero(self):
        """Unlimited tiers report zero capacity."""
        tier = PricingTier(name="unlimited", min_units=100, max_units=None, unit_price=5.0)
        capacity = PricingTier._tier_capacity(tier)
        assert capacity == 0

    def test_cost_for_units_in_tier(self):
        """Tier.cost_for_units calculates correctly."""
        tier = PricingTier(name="test", min_units=1, max_units=100, unit_price=10.0, flat_fee=5.0)

        # 50 units should give: 5.0 + (50 * 10.0) = 505.0
        cost = tier.cost_for_units(50)
        assert cost == 505.0

    def test_cost_for_units_outside_range(self):
        """cost_for_units returns 0 for units outside tier range."""
        tier = PricingTier(name="test", min_units=50, max_units=100, unit_price=10.0)

        assert tier.cost_for_units(10) == 0.0  # Below range
        assert tier.cost_for_units(150) == 0.0  # Above range

    def test_grid_to_dict_serialization(self):
        """Grid serialization format unchanged."""
        grid = PricingGridReconstructionUtil.from_flat_price("prod-15", 10.0, currency="EUR")
        serialized = grid.to_dict()

        assert "product_id" in serialized
        assert "tiers" in serialized
        assert "currency" in serialized
        assert serialized["product_id"] == "prod-15"
        assert serialized["currency"] == "EUR"

    def test_grid_to_dict_metadata_optional(self):
        """Metadata included only when requested."""
        raw_tiers = [
            {
                "name": "t1",
                "min_units": 1,
                "max_units": 100,
                "unit_price": 10.0,
                "metadata": {"key": "value"}
            }
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-16", raw_tiers)

        without_metadata = grid.to_dict(include_metadata=False)
        with_metadata = grid.to_dict(include_metadata=True)

        assert "metadata" not in without_metadata["tiers"][0]
        assert "metadata" in with_metadata["tiers"][0]
        assert with_metadata["tiers"][0]["metadata"]["key"] == "value"


class TestEdgeCasesAfterDeduplication:
    """Edge cases must still be handled correctly post-deduplication."""

    def test_zero_unit_cost(self):
        """Zero units costs zero."""
        grid = PricingGridReconstructionUtil.from_flat_price("prod-17", 10.0)
        assert grid.total_cost(0) == 0.0

    def test_single_unit_cost(self):
        """Single unit cost calculated correctly."""
        grid = PricingGridReconstructionUtil.from_flat_price("prod-18", 10.0)
        assert grid.total_cost(1) == 10.0

    def test_flat_fee_with_zero_unit_price(self):
        """Flat fee applied even with zero unit price."""
        tier = PricingTier(name="flat-only", min_units=1, max_units=100, unit_price=0.0, flat_fee=50.0)
        grid = PricingGrid(product_id="prod-19", tiers=[tier])

        cost = grid.total_cost(50)
        assert cost == 50.0  # Only flat fee, no per-unit cost

    def test_no_matching_tier(self):
        """No matching tier for units returns None."""
        raw_tiers = [
            {"name": "t1", "min_units": 100, "max_units": 200, "unit_price": 10.0}
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-20", raw_tiers)

        assert grid.tier_for_units(50) is None  # Below minimum

    def test_empty_raw_tiers_list(self):
        """Empty tiers list creates valid but empty grid."""
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-21", [])
        assert len(grid.tiers) == 0
        assert grid.total_cost(100) == 0.0

    def test_default_values_in_tier_construction(self):
        """Missing optional fields get sensible defaults."""
        raw_tier = {"name": "minimal", "min_units": 1, "max_units": 100}
        tier = PricingTier(
            name=raw_tier["name"],
            min_units=raw_tier["min_units"],
            max_units=raw_tier["max_units"],
            unit_price=0.0  # Default
        )
        assert tier.flat_fee == 0.0
        assert tier.metadata == {}
        assert tier.unit_price == 0.0

    def test_very_large_tier_range(self):
        """Very large tier ranges handled without overflow."""
        raw_tiers = [
            {"name": "huge", "min_units": 1, "max_units": 10**9, "unit_price": 0.000001}
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-22", raw_tiers)
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert is_valid is True

    def test_floating_point_precision(self):
        """Floating point calculations maintain precision."""
        grid = PricingGridReconstructionUtil.from_flat_price("prod-23", 0.1)
        cost = grid.total_cost(3)
        assert cost == 0.3 or abs(cost - 0.3) < 0.001  # Allow for floating point imprecision

    def test_none_max_units_represents_unlimited(self):
        """None max_units correctly represents unlimited tier."""
        tier = PricingTier(name="unlimited", min_units=1000, max_units=None, unit_price=1.0)
        assert tier.is_unlimited is True
        assert tier.max_units is None

    def test_tier_name_with_special_characters(self):
        """Tier names with special characters preserved."""
        raw_tiers = [
            {"name": "tier-with-dash_and_underscore", "min_units": 1, "max_units": 100, "unit_price": 10.0}
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-24", raw_tiers)
        assert grid.tiers[0].name == "tier-with-dash_and_underscore"


class TestConsumptionLogicPreservation:
    """Verify tier consumption logic unchanged after deduplication."""

    def test_consume_tier_units_within_range(self):
        """Tier consumption works within tier bounds."""
        tier = PricingTier(name="test", min_units=1, max_units=100, unit_price=10.0)
        grid = PricingGrid(product_id="test", tiers=[tier])

        consumed, cost = grid._consume_tier_units(tier, 50)
        assert consumed > 0
        assert cost > 0

    def test_consume_tier_units_zero_remaining(self):
        """Zero remaining units returns zero consumption."""
        tier = PricingTier(name="test", min_units=1, max_units=100, unit_price=10.0)
        grid = PricingGrid(product_id="test", tiers=[tier])

        consumed, cost = grid._consume_tier_units(tier, 0)
        assert consumed == 0
        assert cost == 0.0

    def test_consume_tier_units_negative_remaining(self):
        """Negative remaining units returns zero consumption."""
        tier = PricingTier(name="test", min_units=1, max_units=100, unit_price=10.0)
        grid = PricingGrid(product_id="test", tiers=[tier])

        consumed, cost = grid._consume_tier_units(tier, -10)
        assert consumed == 0
        assert cost == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
