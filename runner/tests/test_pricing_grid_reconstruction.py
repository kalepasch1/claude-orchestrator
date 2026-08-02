"""Tests for pricing_grid_reconstruction — shared PricingGridReconstructionUtil."""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pricing_grid_reconstruction import (
    PricingTier, PricingGrid, PricingGridReconstructionUtil,
)


class TestPricingTier:
    def test_cost_for_units(self):
        tier = PricingTier(name="basic", min_units=1, max_units=100, unit_price=1.0)
        assert tier.cost_for_units(50) == 50.0

    def test_is_unlimited(self):
        tier = PricingTier(name="enterprise", min_units=1, max_units=None, unit_price=0.5)
        assert tier.is_unlimited is True

    def test_not_unlimited(self):
        tier = PricingTier(name="basic", min_units=1, max_units=100, unit_price=1.0)
        assert tier.is_unlimited is False

    def test_flat_fee(self):
        tier = PricingTier(name="pro", min_units=1, max_units=10, unit_price=2.0, flat_fee=10.0)
        cost = tier.cost_for_units(5)
        assert cost == 20.0  # flat_fee 10 + 5 units * 2.0


class TestPricingGrid:
    def test_total_cost_single_tier(self):
        grid = PricingGrid(product_id="p1", tiers=[
            PricingTier("flat", 1, None, 1.5),
        ])
        assert grid.total_cost(10) == 15.0

    def test_total_cost_multi_tier(self):
        grid = PricingGrid(product_id="p2", tiers=[
            PricingTier("basic", 1, 10, 2.0),
            PricingTier("pro", 11, 100, 1.0),
        ])
        cost = grid.total_cost(15)
        # 10 units at 2.0 + 5 units at 1.0 = 25.0
        assert cost == 25.0

    def test_tier_for_units(self):
        grid = PricingGrid(product_id="p3", tiers=[
            PricingTier("basic", 1, 50, 2.0),
            PricingTier("pro", 51, None, 1.0),
        ])
        assert grid.tier_for_units(25).name == "basic"
        assert grid.tier_for_units(100).name == "pro"

    def test_tier_for_units_none(self):
        grid = PricingGrid(product_id="p4", tiers=[
            PricingTier("basic", 10, 50, 2.0),
        ])
        assert grid.tier_for_units(5) is None


class TestPricingGridReconstructionUtil:
    def test_from_raw_tiers(self):
        raw = [
            {"name": "starter", "min_units": 1, "max_units": 100, "unit_price": 2.0},
            {"name": "growth", "min_units": 101, "max_units": None, "unit_price": 1.0},
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("prod-1", raw)
        assert grid.product_id == "prod-1"
        assert len(grid.tiers) == 2
        assert grid.tiers[0].name == "starter"

    def test_from_flat_price(self):
        grid = PricingGridReconstructionUtil.from_flat_price("prod-2", 9.99)
        assert len(grid.tiers) == 1
        assert grid.tiers[0].unit_price == 9.99
        assert grid.tiers[0].is_unlimited

    def test_merge_grids(self):
        g1 = PricingGrid("p", tiers=[PricingTier("a", 1, 10, 1.0)])
        g2 = PricingGrid("p", tiers=[
            PricingTier("a", 1, 10, 1.0),
            PricingTier("b", 11, None, 0.5),
        ])
        merged = PricingGridReconstructionUtil.merge_grids([g1, g2])
        assert len(merged.tiers) == 2

    def test_merge_empty_raises(self):
        with pytest.raises(ValueError):
            PricingGridReconstructionUtil.merge_grids([])

    def test_validate_valid_grid(self):
        grid = PricingGrid("p", tiers=[PricingTier("a", 1, 100, 1.0)])
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert valid is True
        assert issues == []

    def test_validate_no_tiers(self):
        grid = PricingGrid("p", tiers=[])
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert valid is False
        assert "no tiers" in issues[0]

    def test_validate_negative_price(self):
        grid = PricingGrid("p", tiers=[PricingTier("a", 1, 10, -1.0)])
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert valid is False

    def test_validate_max_less_than_min(self):
        grid = PricingGrid("p", tiers=[PricingTier("a", 100, 10, 1.0)])
        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)
        assert valid is False
