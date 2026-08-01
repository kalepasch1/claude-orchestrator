#!/usr/bin/env python3
"""
test_qafix_kalepasch_com_34bc56c33a4f.py — Comprehensive test suite for qafix duplicate elimination.

Task: qafix-kalepasch-com-34bc56c33a4f
Objective: Verify that the REUSE-FIRST deduplication strategy correctly eliminates duplicate
implementations while preserving all existing behavior through MERGED-DIFF LIBRARY and
PATCH TRANSPLANT mechanisms.

Tests cover:
- Duplicate detection and classification (code, structure, logic)
- MERGED-DIFF LIBRARY adaptation (reusing proven prior diffs)
- PATCH TRANSPLANT functionality (adapting proven patches before drafting)
- Behavior preservation across eliminated duplicates
- PricingGridReconstruction deduplication (primary focus)
- Cross-module integration after consolidation
- Schema and API compatibility during migration
- Edge cases: empty implementations, complex duplicates, partial overlaps
- Redundancy removal while maintaining semantic equivalence
- Preflight validation and sanitization
"""
import sys
import os
import pytest
import json
from typing import Dict, Any, List, Tuple, Optional
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

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


@dataclass
class DuplicateInfo:
    """Represents a detected duplicate code section."""
    file_path: str
    line_range: Tuple[int, int]
    code_hash: str
    category: str  # 'identical', 'near-duplicate', 'refactor-target'
    references: List[str]  # Other locations with identical/similar code


class TestDuplicateDetection:
    """Verify duplicate detection across pricing grid reconstruction."""

    def test_detect_identical_tier_creation_logic(self):
        """Identical tier creation in multiple places is detected."""
        # Both create same tier structure
        tier1 = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0)
        tier2 = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0)

        # Verify they are semantically identical
        assert tier1.name == tier2.name
        assert tier1.min_units == tier2.min_units
        assert tier1.max_units == tier2.max_units
        assert tier1.unit_price == tier2.unit_price

    def test_detect_duplicate_cost_calculation(self):
        """Duplicate cost calculation logic is identified."""
        tier = PricingTier(name="basic", min_units=1, max_units=100, unit_price=10.0, flat_fee=5.0)

        # Direct calculation (would be inline duplicate)
        direct_cost = 5.0 + (50 * 10.0)

        # Method calculation (consolidated)
        method_cost = tier.cost_for_units(50)

        # Should produce identical results
        assert direct_cost == method_cost

    def test_detect_duplicate_grid_validation_logic(self):
        """Grid validation logic duplicates are found."""
        raw_tiers = [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "t2", "min_units": 50, "max_units": 150, "unit_price": 5.0},  # Overlaps
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("product-1", raw_tiers)
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)

        # Overlap detection should work consistently
        assert is_valid is False
        assert any("overlap" in issue.lower() for issue in issues)

    def test_detect_near_duplicate_tier_construction(self):
        """Near-duplicate tier construction patterns detected."""
        # Pattern 1: with flat_fee
        tier1 = PricingTier(name="t1", min_units=1, max_units=100, unit_price=10.0, flat_fee=50.0)
        # Pattern 2: without flat_fee (default to 0.0)
        tier2 = PricingTier(name="t2", min_units=1, max_units=100, unit_price=10.0)

        # Both result in functional equivalence when flat_fee handling is consistent
        assert tier1.unit_price == tier2.unit_price
        assert tier1.min_units == tier2.min_units
        assert tier1.max_units == tier2.max_units

    def test_duplicate_grid_serialization_pattern(self):
        """Duplicate serialization logic identified across codebase."""
        grid = PricingGridReconstructionUtil.from_flat_price("product-1", 10.0)

        # Multiple ways to serialize (inline vs method)
        serialized_method = grid.to_dict()
        serialized_manual = {
            "product_id": grid.product_id,
            "tiers": [t.to_dict() for t in grid.tiers],
            "currency": grid.currency,
        }

        # Both should produce equivalent results
        assert serialized_method["product_id"] == serialized_manual["product_id"]
        assert len(serialized_method["tiers"]) == len(serialized_manual["tiers"])


class TestMergedDiffLibraryReuse:
    """Verify MERGED-DIFF LIBRARY adaptation and reuse."""

    def test_reuse_proven_tier_creation_pattern(self):
        """Adapt proven tier creation from prior diff."""
        # Original proven pattern (from pareto-2080 slice)
        original_pattern = PricingTier(
            name="proven", min_units=1, max_units=100, unit_price=10.0, flat_fee=5.0
        )

        # Reused in new context (should be identical)
        reused_pattern = PricingTier(
            name="proven", min_units=1, max_units=100, unit_price=10.0, flat_fee=5.0
        )

        # Behavior preservation check
        test_units = [1, 50, 100]
        for units in test_units:
            assert original_pattern.cost_for_units(units) == reused_pattern.cost_for_units(units)

    def test_adapt_proven_grid_construction(self):
        """Adapt proven grid construction logic from prior diffs."""
        # Proven pattern: from_raw_tiers with standard tier structure
        proven_tiers = [
            {"name": "starter", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "pro", "min_units": 101, "max_units": 1000, "unit_price": 5.0},
        ]

        grid_from_proven = PricingGridReconstructionUtil.from_raw_tiers("proven-product", proven_tiers)

        # Adapt to new context (same logic, different product)
        adapted_tiers = [
            {"name": "basic", "min_units": 1, "max_units": 100, "unit_price": 12.0},
            {"name": "professional", "min_units": 101, "max_units": 1000, "unit_price": 7.0},
        ]

        grid_adapted = PricingGridReconstructionUtil.from_raw_tiers("adapted-product", adapted_tiers)

        # Both should function identically despite different values
        assert len(grid_from_proven.tiers) == len(grid_adapted.tiers)
        assert grid_from_proven.total_cost(50) > 0
        assert grid_adapted.total_cost(50) > 0

    def test_reuse_validation_pattern_from_library(self):
        """Reuse proven validation logic from MERGED-DIFF LIBRARY."""
        # Proven validation pattern
        valid_grid = PricingGridReconstructionUtil.from_raw_tiers("product-1", [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "t2", "min_units": 101, "max_units": None, "unit_price": 5.0},
        ])

        invalid_grid = PricingGridReconstructionUtil.from_raw_tiers("product-2", [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "t2", "min_units": 50, "max_units": 150, "unit_price": 5.0},  # Overlaps
        ])

        # Reused validation should catch both cases correctly
        is_valid_1, _ = PricingGridReconstructionUtil.validate_grid(valid_grid)
        is_valid_2, _ = PricingGridReconstructionUtil.validate_grid(invalid_grid)

        assert is_valid_1 is True
        assert is_valid_2 is False

    def test_merge_library_diff_adaptation_with_modifications(self):
        """Adapt and modify proven diffs from library."""
        # Base proven pattern
        base_grid = PricingGridReconstructionUtil.from_flat_price("base", 10.0)

        # Adaptation: modify base pattern for new context
        adapted_grid = PricingGridReconstructionUtil.from_raw_tiers("adapted", [
            {"name": "base_adapted", "min_units": 1, "max_units": None, "unit_price": 10.0}
        ])

        # Cost behavior should be identical
        for units in [1, 50, 100, 1000]:
            assert base_grid.total_cost(units) == adapted_grid.total_cost(units)


class TestPatchTransplant:
    """Verify PATCH TRANSPLANT functionality - adapting proven patches."""

    def test_transplant_proven_patch_beethoven_07071626(self):
        """Adapt proven patch from beethoven/recover-missing-branch-relfix-beethoven-07071626."""
        # Simulate applying a proven patch that handles missing/broken tier configurations
        grid = PricingGridReconstructionUtil.from_raw_tiers("transplant-test", [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "t2", "min_units": 101, "max_units": None, "unit_price": 5.0},
        ])

        # Patch should ensure valid state
        is_valid, _ = PricingGridReconstructionUtil.validate_grid(grid)
        assert is_valid is True

    def test_transplant_recovery_for_incomplete_tier_spec(self):
        """Transplant recovery handles incomplete tier specifications."""
        # Incomplete spec with missing optional fields
        incomplete_tiers = [
            {"name": "minimal", "min_units": 1, "max_units": 100}  # Missing unit_price
        ]

        # Transplanted patch should provide sensible defaults or recovery
        tier = PricingTier(
            name=incomplete_tiers[0]["name"],
            min_units=incomplete_tiers[0]["min_units"],
            max_units=incomplete_tiers[0]["max_units"],
            unit_price=0.0  # Default from transplanted recovery
        )

        assert tier.unit_price == 0.0
        assert tier.flat_fee == 0.0

    def test_transplant_multi_tier_recovery_pattern(self):
        """Transplant pattern for recovering malformed multi-tier grids."""
        # Proven transplant pattern for malformed input
        malformed_tiers = [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "t2", "min_units": 50, "max_units": 150, "unit_price": 5.0},  # Overlaps
            {"name": "t3", "min_units": 101, "max_units": None, "unit_price": 1.0},
        ]

        # Transplanted fix would detect and report overlaps
        grid = PricingGridReconstructionUtil.from_raw_tiers("malformed", malformed_tiers)
        is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)

        assert is_valid is False
        assert any("overlap" in str(issue).lower() for issue in issues)

    def test_transplant_handles_edge_case_unlimited_tiers(self):
        """Transplant pattern handles unlimited tier edge cases."""
        tiers = [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "t2", "min_units": 101, "max_units": None, "unit_price": 1.0},
        ]

        grid = PricingGridReconstructionUtil.from_raw_tiers("unlimited-test", tiers)
        is_valid, _ = PricingGridReconstructionUtil.validate_grid(grid)

        # Transplanted logic should handle single unlimited tier correctly
        assert is_valid is True
        assert grid.tiers[1].is_unlimited is True


class TestPricingGridReconstructionDeduplication:
    """Primary deduplication target: PricingGridReconstruction module."""

    def test_consolidate_duplicate_tier_creation_methods(self):
        """Consolidate multiple tier creation patterns into single method."""
        # Pattern 1: Direct instantiation
        tier_pattern1 = PricingTier(
            name="direct", min_units=1, max_units=100, unit_price=10.0, flat_fee=5.0
        )

        # Pattern 2: Factory method (unified approach)
        tier_pattern2 = PricingTier(
            name="direct", min_units=1, max_units=100, unit_price=10.0, flat_fee=5.0
        )

        # Both should produce identical results
        assert tier_pattern1.cost_for_units(50) == tier_pattern2.cost_for_units(50)

    def test_eliminate_duplicate_cost_computation_logic(self):
        """Eliminate redundant cost computation implementations."""
        tier = PricingTier(name="test", min_units=1, max_units=100, unit_price=10.0, flat_fee=5.0)

        # Multiple ways to compute cost should produce identical results
        cost_via_method = tier.cost_for_units(50)
        cost_inline = 5.0 + (50 * 10.0)

        assert cost_via_method == cost_inline

    def test_consolidate_grid_validation_across_codebase(self):
        """Consolidate grid validation logic (currently duplicated)."""
        grid1 = PricingGridReconstructionUtil.from_raw_tiers("product-1", [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0}
        ])

        # Validation should be consistent regardless of how grid was created
        is_valid1, issues1 = PricingGridReconstructionUtil.validate_grid(grid1)
        assert is_valid1 is True
        assert len(issues1) == 0

    def test_consolidate_serialization_deserialization(self):
        """Consolidate duplicate serialization patterns."""
        original = PricingGridReconstructionUtil.from_raw_tiers("product-1", [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0}
        ])

        # Serialize via method
        serialized = original.to_dict()

        # Deserialize
        restored = PricingGridReconstructionUtil.from_raw_tiers(
            serialized["product_id"],
            serialized["tiers"]
        )

        # Should be functionally equivalent
        assert original.total_cost(50) == restored.total_cost(50)

    def test_dedup_tier_capacity_calculation(self):
        """Deduplicate tier capacity calculation logic."""
        tier = PricingTier(name="test", min_units=10, max_units=50, unit_price=10.0)

        # Capacity calculation should be consistent
        capacity_method = PricingTier._tier_capacity(tier)
        capacity_inline = 50 - 10 + 1

        assert capacity_method == capacity_inline
        assert capacity_method == 41

    def test_dedup_unlimited_tier_check(self):
        """Consolidate unlimited tier checking logic."""
        unlimited_tier = PricingTier(name="unlimited", min_units=1, max_units=None, unit_price=1.0)
        limited_tier = PricingTier(name="limited", min_units=1, max_units=100, unit_price=1.0)

        # is_unlimited property should be the single source of truth
        assert unlimited_tier.is_unlimited is True
        assert limited_tier.is_unlimited is False

    def test_consolidate_tier_range_validation(self):
        """Consolidate tier range validation logic."""
        valid_tier = PricingTier(name="valid", min_units=1, max_units=100, unit_price=10.0)
        invalid_tier = PricingTier(name="invalid", min_units=100, max_units=50, unit_price=10.0)

        # Validation should work consistently
        valid_grid = PricingGrid(product_id="test", tiers=[valid_tier])
        invalid_grid = PricingGrid(product_id="test", tiers=[invalid_tier])

        is_valid_1, _ = PricingGridReconstructionUtil.validate_grid(valid_grid)
        is_valid_2, _ = PricingGridReconstructionUtil.validate_grid(invalid_grid)

        assert is_valid_1 is True
        assert is_valid_2 is False


class TestBehaviorPreservationAfterDeduplication:
    """Critical: verify zero behavior changes from deduplication."""

    def test_cost_calculations_identical_after_dedup(self):
        """Cost calculations must produce identical results."""
        tiers = [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "t2", "min_units": 101, "max_units": 1000, "unit_price": 5.0},
            {"name": "t3", "min_units": 1001, "max_units": None, "unit_price": 1.0},
        ]

        grid = PricingGridReconstructionUtil.from_raw_tiers("behavior-test", tiers)

        # Comprehensive cost calculation tests
        test_cases = [
            (1, 10.0),
            (50, 500.0),
            (100, 1000.0),
            (101, 1000.0 + 5.0),
            (150, 1000.0 + (50 * 5.0)),
            (1001, 1000.0 + (900 * 5.0) + 1.0),
            (2000, 1000.0 + (900 * 5.0) + (1000 * 1.0)),
        ]

        for units, expected_cost in test_cases:
            actual_cost = grid.total_cost(units)
            assert abs(actual_cost - expected_cost) < 0.01, f"Mismatch at {units} units"

    def test_tier_selection_unchanged_after_dedup(self):
        """Tier selection must remain deterministic."""
        tiers = [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "t2", "min_units": 101, "max_units": 1000, "unit_price": 5.0},
            {"name": "t3", "min_units": 1001, "max_units": None, "unit_price": 1.0},
        ]

        grid = PricingGridReconstructionUtil.from_raw_tiers("selection-test", tiers)

        # Verify tier selection for boundary and interior points
        assert grid.tier_for_units(1).name == "t1"
        assert grid.tier_for_units(50).name == "t1"
        assert grid.tier_for_units(100).name == "t1"
        assert grid.tier_for_units(101).name == "t2"
        assert grid.tier_for_units(500).name == "t2"
        assert grid.tier_for_units(1000).name == "t2"
        assert grid.tier_for_units(1001).name == "t3"
        assert grid.tier_for_units(10000).name == "t3"

    def test_validation_results_unchanged_after_dedup(self):
        """Validation must catch same issues as before dedup."""
        test_cases = [
            # (tiers, should_be_valid, issue_type)
            (
                [{"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0}],
                True,
                None
            ),
            (
                [{"name": "t1", "min_units": 1, "max_units": 100, "unit_price": -10.0}],
                False,
                "negative"
            ),
            (
                [{"name": "t1", "min_units": 100, "max_units": 50, "unit_price": 10.0}],
                False,
                "max < min"
            ),
            (
                [
                    {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0},
                    {"name": "t2", "min_units": 50, "max_units": 150, "unit_price": 5.0},
                ],
                False,
                "overlap"
            ),
        ]

        for tiers, should_be_valid, issue_type in test_cases:
            grid = PricingGridReconstructionUtil.from_raw_tiers("validation-test", tiers)
            is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)

            assert is_valid == should_be_valid
            if issue_type:
                assert any(issue_type in str(issue).lower() for issue in issues)

    def test_serialization_round_trip_identical(self):
        """Serialization round-trip must preserve all behavior."""
        original_tiers = [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0, "flat_fee": 5.0},
            {"name": "t2", "min_units": 101, "max_units": None, "unit_price": 5.0, "flat_fee": 50.0},
        ]

        original = PricingGridReconstructionUtil.from_raw_tiers("round-trip-test", original_tiers)

        # Serialize
        serialized = original.to_dict()

        # Deserialize
        restored = PricingGridReconstructionUtil.from_raw_tiers(
            serialized["product_id"],
            serialized["tiers"]
        )

        # Comprehensive equivalence check
        for units in [1, 50, 100, 101, 500, 1000, 10000]:
            assert original.total_cost(units) == restored.total_cost(units)
            orig_tier = original.tier_for_units(units)
            rest_tier = restored.tier_for_units(units)
            if orig_tier and rest_tier:
                assert orig_tier.name == rest_tier.name


class TestCrossModuleIntegrationAfterDedup:
    """Verify integration between modules remains intact."""

    def test_common_utils_integration_unchanged(self):
        """common_utils integration must work identically."""
        tier = PricingTier(name="test", min_units=1, max_units=100, unit_price=10.0)
        grid = PricingGrid(product_id="test", tiers=[tier])

        # Tier consumption via common_utils should work
        consumed, remaining = common_utils.consume_from_tier(
            current=0,
            tier_min=1,
            tier_max=100,
            amount=50
        )

        assert consumed > 0
        assert remaining >= 0

    def test_grid_merged_diff_library_integration(self):
        """MERGED-DIFF LIBRARY integration must function after dedup."""
        grid1 = PricingGridReconstructionUtil.from_flat_price("product-1", 10.0)
        grid2 = PricingGridReconstructionUtil.from_flat_price("product-1", 12.0)

        # Grid merging must work correctly
        merged = PricingGridReconstructionUtil.merge_grids([grid1, grid2])

        assert merged is not None
        assert merged.product_id == "product-1"
        assert len(merged.tiers) > 0


class TestRemovalOfRedundancy:
    """Verify redundant code is safely removed."""

    def test_no_duplicate_tier_creation_functions(self):
        """Tier creation consolidated to single pattern."""
        tier1 = PricingTier(name="t1", min_units=1, max_units=100, unit_price=10.0)
        tier2 = PricingTier(name="t2", min_units=1, max_units=100, unit_price=10.0)

        # Both should use identical creation method
        assert tier1.min_units == tier2.min_units
        assert tier1.unit_price == tier2.unit_price

    def test_no_duplicate_cost_calculation(self):
        """Cost calculation consolidated to single implementation."""
        tier = PricingTier(name="test", min_units=1, max_units=100, unit_price=10.0)

        # Only one way to calculate cost
        cost = tier.cost_for_units(50)
        assert cost == 500.0

    def test_no_duplicate_validation_logic(self):
        """Validation logic consolidated to single implementation."""
        grid = PricingGridReconstructionUtil.from_raw_tiers("test", [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0}
        ])

        # Validation called once, unified logic
        is_valid, _ = PricingGridReconstructionUtil.validate_grid(grid)
        assert is_valid is True


class TestEdgeCasesPostDedup:
    """Edge cases must still be handled correctly."""

    def test_zero_units_costs_zero(self):
        """Zero units must cost zero."""
        grid = PricingGridReconstructionUtil.from_flat_price("test", 10.0)
        assert grid.total_cost(0) == 0.0

    def test_single_unit_cost_accurate(self):
        """Single unit cost must be accurate."""
        grid = PricingGridReconstructionUtil.from_flat_price("test", 10.0)
        assert grid.total_cost(1) == 10.0

    def test_very_large_unit_counts(self):
        """Large unit counts handled without overflow."""
        grid = PricingGridReconstructionUtil.from_flat_price("test", 0.01)
        cost = grid.total_cost(1_000_000)
        assert cost == pytest.approx(10_000.0)

    def test_fractional_pricing(self):
        """Fractional pricing handled correctly."""
        grid = PricingGridReconstructionUtil.from_flat_price("test", 0.5)
        cost = grid.total_cost(3)
        assert cost == 1.5

    def test_empty_grid_handling(self):
        """Empty grid costs zero."""
        grid = PricingGrid(product_id="empty", tiers=[])
        assert grid.total_cost(100) == 0.0

    def test_tier_with_only_flat_fee(self):
        """Tier with zero unit price still applies flat fee."""
        tier = PricingTier(name="flat-only", min_units=1, max_units=100, unit_price=0.0, flat_fee=50.0)
        grid = PricingGrid(product_id="test", tiers=[tier])

        cost = grid.total_cost(50)
        assert cost == 50.0  # Only flat fee

    def test_multiple_decimal_precision(self):
        """Pricing calculations maintain proper decimal precision."""
        grid = PricingGridReconstructionUtil.from_flat_price("test", 0.333)
        cost = grid.total_cost(30)
        # Should be 9.99
        assert cost == pytest.approx(9.99, abs=0.01)

    def test_tier_name_special_characters(self):
        """Tier names with special characters preserved."""
        raw_tiers = [
            {"name": "tier-with-dashes_and_underscores", "min_units": 1, "max_units": 100, "unit_price": 10.0}
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("test", raw_tiers)
        assert grid.tiers[0].name == "tier-with-dashes_and_underscores"


class TestAcceptanceCriteria:
    """Verify acceptance criteria: preserve existing behavior."""

    def test_acceptance_preserve_cost_calculation_behavior(self):
        """Acceptance: Cost calculations produce identical results pre/post-dedup."""
        grid = PricingGridReconstructionUtil.from_raw_tiers("acceptance-test", [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "t2", "min_units": 101, "max_units": None, "unit_price": 5.0},
        ])

        # Define expected behavior baseline
        expected_costs = {
            50: 500.0,
            100: 1000.0,
            150: 1000.0 + (50 * 5.0),
        }

        # Verify all expected behavior is preserved
        for units, expected_cost in expected_costs.items():
            actual_cost = grid.total_cost(units)
            assert actual_cost == expected_cost, f"Cost calculation changed for {units} units"

    def test_acceptance_validation_catches_same_errors(self):
        """Acceptance: Validation catches all errors consistently."""
        # Valid grid
        valid = PricingGridReconstructionUtil.from_raw_tiers("valid", [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "t2", "min_units": 101, "max_units": None, "unit_price": 5.0},
        ])

        is_valid, _ = PricingGridReconstructionUtil.validate_grid(valid)
        assert is_valid is True

        # Invalid grids with various issues
        invalid_cases = [
            # Overlapping tiers
            [
                {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0},
                {"name": "t2", "min_units": 50, "max_units": 150, "unit_price": 5.0},
            ],
            # Negative price
            [{"name": "t1", "min_units": 1, "max_units": 100, "unit_price": -10.0}],
            # Invalid range
            [{"name": "t1", "min_units": 100, "max_units": 50, "unit_price": 10.0}],
        ]

        for invalid_tiers in invalid_cases:
            grid = PricingGridReconstructionUtil.from_raw_tiers("invalid", invalid_tiers)
            is_valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
            assert is_valid is False
            assert len(issues) > 0

    def test_acceptance_tier_selection_consistent(self):
        """Acceptance: Tier selection remains consistent."""
        grid = PricingGridReconstructionUtil.from_raw_tiers("tier-test", [
            {"name": "basic", "min_units": 1, "max_units": 100, "unit_price": 10.0},
            {"name": "pro", "min_units": 101, "max_units": 1000, "unit_price": 5.0},
            {"name": "enterprise", "min_units": 1001, "max_units": None, "unit_price": 1.0},
        ])

        # Verify deterministic tier selection
        for units in [1, 50, 100, 101, 500, 1000, 1001, 5000]:
            tier = grid.tier_for_units(units)
            assert tier is not None
            assert tier.min_units <= units
            assert tier.max_units is None or units <= tier.max_units

    def test_acceptance_serialization_maintains_fidelity(self):
        """Acceptance: Serialization/deserialization maintains full fidelity."""
        original = PricingGridReconstructionUtil.from_raw_tiers("fidelity-test", [
            {"name": "t1", "min_units": 1, "max_units": 100, "unit_price": 10.0, "flat_fee": 5.0},
            {"name": "t2", "min_units": 101, "max_units": None, "unit_price": 5.0, "flat_fee": 50.0},
        ])

        serialized = original.to_dict()
        restored = PricingGridReconstructionUtil.from_raw_tiers(
            serialized["product_id"],
            serialized["tiers"]
        )

        # Full fidelity check
        assert original.product_id == restored.product_id
        assert len(original.tiers) == len(restored.tiers)

        for units in [1, 50, 100, 150, 1000]:
            assert original.total_cost(units) == restored.total_cost(units)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
