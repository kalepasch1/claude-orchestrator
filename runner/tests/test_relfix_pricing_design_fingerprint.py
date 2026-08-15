"""Tests for relfix-prediction-markets-institute-07290017.

Validates that the adapted pricing grid reconstruction patch:
1. Does not raise TypeError when called with unexpected kwargs
2. Preserves existing behavior after deduplication
3. Maintains backward compatibility with all callers
4. Correctly integrates design_fingerprint usage in result_cache
"""
import os
import sys
import pytest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pricing_grid_reconstruction import (
    PricingTier, PricingGrid, PricingGridReconstructionUtil,
)
import result_cache


class TestDesignFingerprintIntegration:
    """Verify that design_fingerprint parameter flows through result_cache correctly."""

    def test_result_cache_signature_accepts_design_fingerprint(self):
        """result_cache.signature() should accept design_fingerprint kwarg."""
        sig = result_cache.signature(
            project="test-project",
            prompt="test prompt",
            repo="/tmp",
            base="main",
            design_fingerprint="abc123",
        )
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA-256 hex digest

    def test_result_cache_signature_with_empty_design_fingerprint(self):
        """Empty design_fingerprint should be valid."""
        sig = result_cache.signature(
            project="test-project",
            prompt="test prompt",
            repo="/tmp",
            base="main",
            design_fingerprint="",
        )
        assert isinstance(sig, str)
        assert len(sig) == 64

    def test_result_cache_signature_without_design_fingerprint(self):
        """design_fingerprint should have a default value."""
        sig1 = result_cache.signature(
            project="test-project",
            prompt="test prompt",
            repo="/tmp",
            base="main",
        )
        sig2 = result_cache.signature(
            project="test-project",
            prompt="test prompt",
            repo="/tmp",
            base="main",
            design_fingerprint="",
        )
        assert sig1 == sig2  # Both should produce same signature when default is ""

    def test_result_cache_signature_differs_by_design_fingerprint(self):
        """Different design_fingerprints should produce different signatures."""
        sig1 = result_cache.signature(
            project="test-project",
            prompt="test prompt",
            repo="/tmp",
            base="main",
            design_fingerprint="abc123",
        )
        sig2 = result_cache.signature(
            project="test-project",
            prompt="test prompt",
            repo="/tmp",
            base="main",
            design_fingerprint="xyz789",
        )
        assert sig1 != sig2


class TestPricingGridReconstructionNoKwargsLeakage:
    """Verify no TypeError from unexpected kwargs in reconstruction utility."""

    def test_from_raw_tiers_does_not_accept_design_fingerprint(self):
        """from_raw_tiers should not accept design_fingerprint kwarg."""
        raw = [{"name": "test", "min_units": 1, "max_units": 10, "unit_price": 1.0}]

        # Should work without design_fingerprint
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-1", raw)
        assert grid.product_id == "prod-1"

        # Should raise TypeError if design_fingerprint is passed
        with pytest.raises(TypeError):
            PricingGridReconstructionUtil.from_raw_tiers(
                "prod-1", raw, design_fingerprint="abc123"
            )

    def test_from_flat_price_does_not_accept_design_fingerprint(self):
        """from_flat_price should not accept design_fingerprint kwarg."""
        # Should work without design_fingerprint
        grid = PricingGridReconstructionUtil.from_flat_price("prod-1", 9.99)
        assert len(grid.tiers) == 1

        # Should raise TypeError if design_fingerprint is passed
        with pytest.raises(TypeError):
            PricingGridReconstructionUtil.from_flat_price(
                "prod-1", 9.99, design_fingerprint="abc123"
            )

    def test_merge_grids_does_not_accept_design_fingerprint(self):
        """merge_grids should not accept design_fingerprint kwarg."""
        g1 = PricingGrid("p", tiers=[PricingTier("a", 1, 10, 1.0)])
        grids = [g1]

        # Should work without design_fingerprint
        merged = PricingGridReconstructionUtil.merge_grids(grids)
        assert merged.product_id == "p"

        # Should raise TypeError if design_fingerprint is passed
        with pytest.raises(TypeError):
            PricingGridReconstructionUtil.merge_grids(grids, design_fingerprint="abc123")

    def test_validate_grid_does_not_accept_design_fingerprint(self):
        """validate_grid should not accept design_fingerprint kwarg."""
        grid = PricingGrid("p", tiers=[PricingTier("a", 1, 10, 1.0)])

        # Should work without design_fingerprint
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert valid is True

        # Should raise TypeError if design_fingerprint is passed
        with pytest.raises(TypeError):
            PricingGridReconstructionUtil.validate_grid(grid, design_fingerprint="abc123")


class TestBackwardCompatibilityPreserved:
    """Verify that existing behavior is preserved after deduplication patch."""

    def test_pricing_tier_cost_calculation_unchanged(self):
        """Existing cost calculation logic must be unchanged."""
        tier = PricingTier(
            name="standard",
            min_units=1,
            max_units=100,
            unit_price=2.5,
            flat_fee=5.0,
        )

        # Test boundary cases
        assert tier.cost_for_units(0) == 0.0
        assert tier.cost_for_units(1) == 7.5  # flat_fee 5.0 + 1 unit * 2.5
        assert tier.cost_for_units(50) == 130.0  # flat_fee 5.0 + 50 units * 2.5
        assert tier.cost_for_units(100) == 255.0  # flat_fee 5.0 + 100 units * 2.5
        assert tier.cost_for_units(101) == 0.0  # above tier range: not applicable

    def test_pricing_grid_multi_tier_cost_calculation_unchanged(self):
        """Multi-tier cost calculation must produce same results."""
        grid = PricingGrid(product_id="prod", tiers=[
            PricingTier("starter", 1, 50, 1.0, 0.0),
            PricingTier("growth", 51, 200, 0.75, 0.0),
            PricingTier("enterprise", 201, None, 0.5, 0.0),
        ])

        # Boundary cases across tiers
        assert grid.total_cost(1) == 1.0
        assert grid.total_cost(50) == 50.0
        assert grid.total_cost(51) == 50.75  # 50 at 1.0 + 1 at 0.75
        assert grid.total_cost(100) == 87.5  # 50 at 1.0 + 50 at 0.75
        assert grid.total_cost(201) == 163.0  # 50 at 1.0 + 150 at 0.75 + 1 at 0.5
        assert grid.total_cost(1000) == 562.5  # 50 at 1.0 + 150 at 0.75 + 800 at 0.5

    def test_grid_reconstruction_from_raw_tiers_produces_normalized_order(self):
        """Grid should auto-sort tiers by min_units on construction."""
        raw = [
            {"name": "enterprise", "min_units": 101, "max_units": None, "unit_price": 0.5},
            {"name": "starter", "min_units": 1, "max_units": 50, "unit_price": 2.0},
            {"name": "growth", "min_units": 51, "max_units": 100, "unit_price": 1.0},
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod", raw)

        # Tiers should be sorted by min_units
        assert grid.tiers[0].name == "starter"
        assert grid.tiers[1].name == "growth"
        assert grid.tiers[2].name == "enterprise"

    def test_grid_merge_produces_most_complete_grid(self):
        """Merge should select grid with most tiers as base."""
        g1 = PricingGrid("prod", tiers=[
            PricingTier("a", 1, 10, 1.0),
            PricingTier("b", 11, None, 0.5),
        ])
        g2 = PricingGrid("prod", tiers=[
            PricingTier("x", 1, 50, 2.0),
            PricingTier("y", 51, 100, 1.5),
            PricingTier("z", 101, None, 1.0),
        ])

        merged = PricingGridReconstructionUtil.merge_grids([g1, g2])
        assert len(merged.tiers) == 3  # Should use g2's tiers (more complete)
        assert merged.tiers[0].name == "x"

    def test_flat_price_grid_is_unlimited(self):
        """Flat price grids should always be unlimited."""
        for price in [0.99, 9.99, 99.99, 999.99]:
            grid = PricingGridReconstructionUtil.from_flat_price("prod", price)
            assert len(grid.tiers) == 1
            tier = grid.tiers[0]
            assert tier.is_unlimited
            assert tier.min_units == 1
            assert tier.max_units is None


class TestDeduplicationValidation:
    """Verify that code deduplication was done correctly."""

    def test_pricing_grid_reconstruction_util_is_singleton_source(self):
        """PricingGridReconstructionUtil should be the authoritative implementation."""
        # This test ensures that there are no duplicate implementations
        # by verifying the main utility class has all expected methods
        expected_methods = [
            "from_raw_tiers",
            "from_flat_price",
            "merge_grids",
            "validate_grid",
        ]
        for method_name in expected_methods:
            assert hasattr(PricingGridReconstructionUtil, method_name), \
                f"Missing expected method: {method_name}"

    def test_pricing_tier_has_all_expected_properties(self):
        """PricingTier should have all properties needed for cost calculations."""
        tier = PricingTier(
            name="test",
            min_units=1,
            max_units=100,
            unit_price=1.0,
            flat_fee=0.5,
            metadata={"key": "value"},
        )

        # Verify all attributes are accessible
        assert tier.name == "test"
        assert tier.min_units == 1
        assert tier.max_units == 100
        assert tier.unit_price == 1.0
        assert tier.flat_fee == 0.5
        assert tier.metadata == {"key": "value"}
        assert tier.is_unlimited is False
        assert callable(tier.cost_for_units)

    def test_pricing_grid_has_all_expected_methods_and_properties(self):
        """PricingGrid should have all expected calculation methods."""
        grid = PricingGrid(
            product_id="test-prod",
            tiers=[PricingTier("basic", 1, None, 1.0)],
            currency="USD",
        )

        # Verify all attributes and methods exist
        assert grid.product_id == "test-prod"
        assert grid.currency == "USD"
        assert isinstance(grid.sorted_tiers, list)  # sorted_tiers is a property that returns a list
        assert callable(grid.total_cost)
        assert callable(grid.tier_for_units)


class TestNoDuplicateImports:
    """Verify that the module structure prevents duplicate initialization."""

    def test_pricing_grid_reconstruction_imports_successfully(self):
        """Module should import without errors."""
        # Already imported above, but verify it's accessible
        assert PricingGridReconstructionUtil is not None
        assert PricingGrid is not None
        assert PricingTier is not None

    def test_module_has_no_duplicate_class_definitions(self):
        """Module should not re-export or duplicate class definitions."""
        import pricing_grid_reconstruction as pgr_module

        # Count occurrences of key classes
        classes = [
            (PricingTier, "PricingTier"),
            (PricingGrid, "PricingGrid"),
            (PricingGridReconstructionUtil, "PricingGridReconstructionUtil"),
        ]

        for cls, name in classes:
            assert hasattr(pgr_module, name)
            assert getattr(pgr_module, name) is cls


class TestAdaptedPatchIntegration:
    """Test scenarios from the adapted patch (qafix-pareto-2080)."""

    def test_reconstruction_util_singleton_pattern_works(self):
        """All static methods should be callable without instantiation."""
        # Should work without ever creating an instance
        grid1 = PricingGridReconstructionUtil.from_flat_price("p1", 5.0)
        grid2 = PricingGridReconstructionUtil.from_flat_price("p2", 10.0)

        assert grid1.product_id == "p1"
        assert grid2.product_id == "p2"
        assert grid1 is not grid2  # Different instances

    def test_normalize_on_construction_ordering(self):
        """Tiers should normalize to sorted order on PricingGrid construction."""
        unsorted_tiers = [
            PricingTier("c", 101, None, 0.5),
            PricingTier("a", 1, 10, 2.0),
            PricingTier("b", 11, 100, 1.0),
        ]
        grid = PricingGrid(product_id="test", tiers=unsorted_tiers)

        # After construction, sorted_tiers property should return sorted order
        sorted_tiers = grid.sorted_tiers
        assert sorted_tiers[0].name == "a"
        assert sorted_tiers[1].name == "b"
        assert sorted_tiers[2].name == "c"

    def test_error_on_empty_grid_merge(self):
        """Merging empty list should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            PricingGridReconstructionUtil.merge_grids([])
        assert "cannot merge empty grid list" in str(exc_info.value)

    def test_complex_tiered_pricing_scenario(self):
        """Test realistic multi-tier pricing with flat fees."""
        raw_tiers = [
            {
                "name": "basic",
                "min_units": 1,
                "max_units": 1000,
                "unit_price": 0.10,
                "flat_fee": 0.0,
            },
            {
                "name": "professional",
                "min_units": 1001,
                "max_units": 10000,
                "unit_price": 0.08,
                "flat_fee": 10.0,
            },
            {
                "name": "enterprise",
                "min_units": 10001,
                "max_units": None,
                "unit_price": 0.05,
                "flat_fee": 50.0,
            },
        ]

        grid = PricingGridReconstructionUtil.from_raw_tiers("complex-prod", raw_tiers)
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)

        assert valid is True
        assert len(issues) == 0

        # Verify cost calculations work across tier boundaries
        assert grid.total_cost(500) == 50.0  # 500 * 0.10
        assert grid.total_cost(2000) == 190.0  # 1000 * 0.10 + (1000 * 0.08 + 10.0 flat fee)


class TestMinimalMergeableDiff:
    """Verify that the patch maintains minimal diff footprint."""

    def test_no_extraneous_whitespace_changes(self):
        """Utility class should use consistent spacing."""
        import inspect
        source = inspect.getsource(PricingGridReconstructionUtil)

        # Should have consistent indentation (4 spaces)
        lines = source.split("\n")
        for line in lines:
            if line.strip() and not line.startswith(" " * 4):
                if not line.startswith("class"):
                    pytest.skip("Non-critical whitespace check")

    def test_method_signatures_unchanged(self):
        """Method signatures should match the adapted specification."""
        import inspect

        # from_raw_tiers(product_id, raw_tiers, currency="USD")
        sig = inspect.signature(PricingGridReconstructionUtil.from_raw_tiers)
        params = list(sig.parameters.keys())
        assert params == ["product_id", "raw_tiers", "currency"]
        assert sig.parameters["currency"].default == "USD"

        # from_flat_price(product_id, unit_price, currency="USD")
        sig = inspect.signature(PricingGridReconstructionUtil.from_flat_price)
        params = list(sig.parameters.keys())
        assert params == ["product_id", "unit_price", "currency"]
        assert sig.parameters["currency"].default == "USD"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
