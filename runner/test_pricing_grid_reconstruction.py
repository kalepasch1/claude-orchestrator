#!/usr/bin/env python3
"""Tests for pricing_grid_reconstruction.py - pricing grid reconstruction utilities."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pricing_grid_reconstruction as pgr


# --- PricingTier tests ---

def test_tier_basic_creation():
    tier = pgr.PricingTier(name="basic", min_units=1, max_units=100, unit_price=5.0)
    assert tier.name == "basic"
    assert tier.min_units == 1
    assert tier.max_units == 100
    assert tier.unit_price == 5.0
    assert tier.flat_fee == 0.0


def test_tier_with_flat_fee():
    tier = pgr.PricingTier(name="premium", min_units=101, max_units=None,
                           unit_price=3.0, flat_fee=10.0)
    assert tier.flat_fee == 10.0
    assert tier.is_unlimited is True


def test_tier_is_unlimited():
    tier_limited = pgr.PricingTier(name="limited", min_units=1, max_units=100, unit_price=5.0)
    tier_unlimited = pgr.PricingTier(name="unlimited", min_units=101, max_units=None, unit_price=2.0)
    assert tier_limited.is_unlimited is False
    assert tier_unlimited.is_unlimited is True


def test_tier_cost_for_units_single_unit():
    tier = pgr.PricingTier(name="tier1", min_units=1, max_units=10, unit_price=5.0)
    cost = tier.cost_for_units(1)
    assert cost == 5.0


def test_tier_cost_for_units_multiple():
    tier = pgr.PricingTier(name="tier1", min_units=1, max_units=100, unit_price=5.0)
    cost = tier.cost_for_units(10)
    assert cost == 50.0


def test_tier_cost_for_units_with_flat_fee():
    tier = pgr.PricingTier(name="tier1", min_units=1, max_units=100,
                           unit_price=5.0, flat_fee=10.0)
    cost = tier.cost_for_units(10)
    assert cost == 60.0


def test_tier_cost_below_minimum():
    tier = pgr.PricingTier(name="tier1", min_units=50, max_units=100, unit_price=5.0)
    cost = tier.cost_for_units(10)
    assert cost == 0.0


def test_tier_cost_exactly_at_minimum():
    tier = pgr.PricingTier(name="tier1", min_units=50, max_units=100, unit_price=5.0)
    cost = tier.cost_for_units(50)
    assert cost > 0.0


def test_tier_cost_above_maximum():
    tier = pgr.PricingTier(name="tier1", min_units=1, max_units=10, unit_price=5.0)
    cost = tier.cost_for_units(20)
    # Should only charge for units 1-10
    assert cost <= 50.0


def test_tier_cost_unlimited_tier():
    tier = pgr.PricingTier(name="tier1", min_units=1, max_units=None, unit_price=5.0)
    cost = tier.cost_for_units(1000)
    assert cost > 0.0


def test_tier_metadata():
    metadata = {"region": "us-east", "sla": "99.9%"}
    tier = pgr.PricingTier(name="tier1", min_units=1, max_units=100,
                           unit_price=5.0, metadata=metadata)
    assert tier.metadata == metadata


# --- PricingGrid tests ---

def test_grid_creation():
    tiers = [
        pgr.PricingTier(name="tier1", min_units=1, max_units=100, unit_price=5.0),
        pgr.PricingTier(name="tier2", min_units=101, max_units=None, unit_price=3.0),
    ]
    grid = pgr.PricingGrid(product_id="prod-123", tiers=tiers)
    assert grid.product_id == "prod-123"
    assert len(grid.tiers) == 2
    assert grid.currency == "USD"


def test_grid_with_custom_currency():
    grid = pgr.PricingGrid(product_id="prod-123", currency="EUR")
    assert grid.currency == "EUR"


def test_grid_sorted_tiers_order():
    tiers = [
        pgr.PricingTier(name="tier2", min_units=101, max_units=None, unit_price=3.0),
        pgr.PricingTier(name="tier1", min_units=1, max_units=100, unit_price=5.0),
    ]
    grid = pgr.PricingGrid(product_id="prod-123", tiers=tiers)
    sorted_tiers = grid.sorted_tiers
    assert sorted_tiers[0].min_units == 1
    assert sorted_tiers[1].min_units == 101


def test_grid_sorted_tiers_empty():
    grid = pgr.PricingGrid(product_id="prod-123", tiers=[])
    assert grid.sorted_tiers == []


def test_grid_total_cost_single_tier():
    tiers = [pgr.PricingTier(name="flat", min_units=1, max_units=None, unit_price=5.0)]
    grid = pgr.PricingGrid(product_id="prod-123", tiers=tiers)
    cost = grid.total_cost(10)
    assert cost == 50.0


def test_grid_total_cost_multiple_tiers():
    tiers = [
        pgr.PricingTier(name="tier1", min_units=1, max_units=100, unit_price=5.0),
        pgr.PricingTier(name="tier2", min_units=101, max_units=None, unit_price=3.0),
    ]
    grid = pgr.PricingGrid(product_id="prod-123", tiers=tiers)
    # 100 units at $5 + 50 units at $3 = $500 + $150 = $650
    cost = grid.total_cost(150)
    assert cost == 650.0


def test_grid_total_cost_within_first_tier():
    tiers = [
        pgr.PricingTier(name="tier1", min_units=1, max_units=100, unit_price=5.0),
        pgr.PricingTier(name="tier2", min_units=101, max_units=None, unit_price=3.0),
    ]
    grid = pgr.PricingGrid(product_id="prod-123", tiers=tiers)
    cost = grid.total_cost(50)
    assert cost == 250.0


def test_grid_total_cost_zero_units():
    tiers = [pgr.PricingTier(name="flat", min_units=1, max_units=None, unit_price=5.0)]
    grid = pgr.PricingGrid(product_id="prod-123", tiers=tiers)
    cost = grid.total_cost(0)
    assert cost == 0.0


def test_grid_total_cost_with_flat_fees():
    tiers = [
        pgr.PricingTier(name="tier1", min_units=1, max_units=100,
                       unit_price=5.0, flat_fee=10.0),
        pgr.PricingTier(name="tier2", min_units=101, max_units=None,
                       unit_price=3.0, flat_fee=5.0),
    ]
    grid = pgr.PricingGrid(product_id="prod-123", tiers=tiers)
    # (10 + 100*5) + (5 + 50*3) = 510 + 155 = 665
    cost = grid.total_cost(150)
    assert cost == 665.0


def test_grid_tier_for_units_exact_match():
    tiers = [
        pgr.PricingTier(name="tier1", min_units=1, max_units=100, unit_price=5.0),
        pgr.PricingTier(name="tier2", min_units=101, max_units=None, unit_price=3.0),
    ]
    grid = pgr.PricingGrid(product_id="prod-123", tiers=tiers)
    tier = grid.tier_for_units(50)
    assert tier.name == "tier1"


def test_grid_tier_for_units_boundary():
    tiers = [
        pgr.PricingTier(name="tier1", min_units=1, max_units=100, unit_price=5.0),
        pgr.PricingTier(name="tier2", min_units=101, max_units=None, unit_price=3.0),
    ]
    grid = pgr.PricingGrid(product_id="prod-123", tiers=tiers)
    tier = grid.tier_for_units(100)
    assert tier.name == "tier1"
    tier = grid.tier_for_units(101)
    assert tier.name == "tier2"


def test_grid_tier_for_units_no_match():
    tiers = [pgr.PricingTier(name="tier1", min_units=50, max_units=100, unit_price=5.0)]
    grid = pgr.PricingGrid(product_id="prod-123", tiers=tiers)
    tier = grid.tier_for_units(10)
    assert tier is None


def test_grid_tier_for_units_empty_grid():
    grid = pgr.PricingGrid(product_id="prod-123", tiers=[])
    tier = grid.tier_for_units(50)
    assert tier is None


def test_grid_effective_date():
    grid = pgr.PricingGrid(product_id="prod-123", effective_date="2024-01-01")
    assert grid.effective_date == "2024-01-01"


# --- PricingGridReconstructionUtil tests ---

def test_util_from_raw_tiers_basic():
    raw_tiers = [
        {"name": "tier1", "min_units": 1, "max_units": 100, "unit_price": 5.0},
        {"name": "tier2", "min_units": 101, "max_units": None, "unit_price": 3.0},
    ]
    grid = pgr.PricingGridReconstructionUtil.from_raw_tiers("prod-123", raw_tiers)
    assert grid.product_id == "prod-123"
    assert len(grid.tiers) == 2
    assert grid.tiers[0].name == "tier1"


def test_util_from_raw_tiers_with_metadata():
    raw_tiers = [
        {
            "name": "tier1", "min_units": 1, "max_units": 100, "unit_price": 5.0,
            "flat_fee": 10.0, "metadata": {"region": "us-east"}
        },
    ]
    grid = pgr.PricingGridReconstructionUtil.from_raw_tiers("prod-123", raw_tiers)
    assert grid.tiers[0].flat_fee == 10.0
    assert grid.tiers[0].metadata["region"] == "us-east"


def test_util_from_raw_tiers_defaults():
    raw_tiers = [{"name": "tier1"}]
    grid = pgr.PricingGridReconstructionUtil.from_raw_tiers("prod-123", raw_tiers)
    tier = grid.tiers[0]
    assert tier.min_units == 0
    assert tier.max_units is None
    assert tier.unit_price == 0.0
    assert tier.flat_fee == 0.0


def test_util_from_raw_tiers_custom_currency():
    raw_tiers = [{"name": "tier1", "unit_price": 5.0}]
    grid = pgr.PricingGridReconstructionUtil.from_raw_tiers("prod-123", raw_tiers, currency="EUR")
    assert grid.currency == "EUR"


def test_util_from_raw_tiers_empty():
    grid = pgr.PricingGridReconstructionUtil.from_raw_tiers("prod-123", [])
    assert len(grid.tiers) == 0


def test_util_from_flat_price():
    grid = pgr.PricingGridReconstructionUtil.from_flat_price("prod-123", 10.0)
    assert grid.product_id == "prod-123"
    assert len(grid.tiers) == 1
    assert grid.tiers[0].unit_price == 10.0
    assert grid.tiers[0].is_unlimited is True


def test_util_from_flat_price_currency():
    grid = pgr.PricingGridReconstructionUtil.from_flat_price("prod-123", 10.0, currency="GBP")
    assert grid.currency == "GBP"


def test_util_merge_grids_single():
    grid1 = pgr.PricingGrid(product_id="prod-123", tiers=[
        pgr.PricingTier(name="tier1", min_units=1, max_units=100, unit_price=5.0)
    ])
    result = pgr.PricingGridReconstructionUtil.merge_grids([grid1])
    assert result.product_id == "prod-123"
    assert len(result.tiers) == 1


def test_util_merge_grids_multiple():
    grid1 = pgr.PricingGrid(product_id="prod-123", tiers=[
        pgr.PricingTier(name="tier1", min_units=1, max_units=100, unit_price=5.0),
        pgr.PricingTier(name="tier2", min_units=101, max_units=None, unit_price=3.0),
    ])
    grid2 = pgr.PricingGrid(product_id="prod-123", tiers=[
        pgr.PricingTier(name="tier1", min_units=1, max_units=50, unit_price=6.0),
    ])
    result = pgr.PricingGridReconstructionUtil.merge_grids([grid1, grid2])
    # Should take grid1 as it has more tiers
    assert len(result.tiers) == 2
    assert result.product_id == "prod-123"


def test_util_merge_grids_empty_raises():
    try:
        pgr.PricingGridReconstructionUtil.merge_grids([])
        assert False, "should raise ValueError"
    except ValueError as e:
        assert "cannot merge empty grid list" in str(e)


def test_util_merge_grids_preserves_properties():
    grid1 = pgr.PricingGrid(
        product_id="prod-123",
        currency="USD",
        effective_date="2024-01-01",
        tiers=[pgr.PricingTier(name="tier1", min_units=1, max_units=100, unit_price=5.0)]
    )
    result = pgr.PricingGridReconstructionUtil.merge_grids([grid1])
    assert result.product_id == "prod-123"
    assert result.currency == "USD"
    assert result.effective_date == "2024-01-01"


def test_util_validate_grid_valid():
    grid = pgr.PricingGrid(product_id="prod-123", tiers=[
        pgr.PricingTier(name="tier1", min_units=1, max_units=100, unit_price=5.0),
        pgr.PricingTier(name="tier2", min_units=101, max_units=None, unit_price=3.0),
    ])
    is_valid, issues = pgr.PricingGridReconstructionUtil.validate_grid(grid)
    assert is_valid is True
    assert len(issues) == 0


def test_util_validate_grid_empty_tiers():
    grid = pgr.PricingGrid(product_id="prod-123", tiers=[])
    is_valid, issues = pgr.PricingGridReconstructionUtil.validate_grid(grid)
    assert is_valid is False
    assert "has no tiers" in issues[0]


def test_util_validate_grid_negative_price():
    grid = pgr.PricingGrid(product_id="prod-123", tiers=[
        pgr.PricingTier(name="tier1", min_units=1, max_units=100, unit_price=-5.0),
    ])
    is_valid, issues = pgr.PricingGridReconstructionUtil.validate_grid(grid)
    assert is_valid is False
    assert any("negative" in issue for issue in issues)


def test_util_validate_grid_max_less_than_min():
    grid = pgr.PricingGrid(product_id="prod-123", tiers=[
        pgr.PricingTier(name="tier1", min_units=100, max_units=50, unit_price=5.0),
    ])
    is_valid, issues = pgr.PricingGridReconstructionUtil.validate_grid(grid)
    assert is_valid is False
    assert any("max < min" in issue for issue in issues)


def test_util_validate_grid_overlapping_tiers():
    grid = pgr.PricingGrid(product_id="prod-123", tiers=[
        pgr.PricingTier(name="tier1", min_units=1, max_units=100, unit_price=5.0),
        pgr.PricingTier(name="tier2", min_units=50, max_units=150, unit_price=3.0),
    ])
    is_valid, issues = pgr.PricingGridReconstructionUtil.validate_grid(grid)
    assert is_valid is False
    assert any("overlap" in issue for issue in issues)


def test_util_validate_grid_non_overlapping_boundaries():
    grid = pgr.PricingGrid(product_id="prod-123", tiers=[
        pgr.PricingTier(name="tier1", min_units=1, max_units=100, unit_price=5.0),
        pgr.PricingTier(name="tier2", min_units=101, max_units=200, unit_price=3.0),
    ])
    is_valid, issues = pgr.PricingGridReconstructionUtil.validate_grid(grid)
    assert is_valid is True
    assert len(issues) == 0


def test_util_validate_grid_single_tier():
    grid = pgr.PricingGrid(product_id="prod-123", tiers=[
        pgr.PricingTier(name="flat", min_units=1, max_units=None, unit_price=5.0),
    ])
    is_valid, issues = pgr.PricingGridReconstructionUtil.validate_grid(grid)
    assert is_valid is True


# --- Integration tests ---

def test_integration_raw_to_cost():
    raw_tiers = [
        {"name": "tier1", "min_units": 1, "max_units": 100, "unit_price": 5.0},
        {"name": "tier2", "min_units": 101, "max_units": None, "unit_price": 3.0},
    ]
    grid = pgr.PricingGridReconstructionUtil.from_raw_tiers("prod-123", raw_tiers)
    cost = grid.total_cost(150)
    assert cost == 650.0


def test_integration_flat_price_calculation():
    grid = pgr.PricingGridReconstructionUtil.from_flat_price("prod-123", 2.5)
    cost = grid.total_cost(1000)
    assert cost == 2500.0


def test_integration_merge_and_validate():
    raw1 = [{"name": "tier1", "min_units": 1, "max_units": 100, "unit_price": 5.0}]
    raw2 = [{"name": "tier1", "min_units": 1, "max_units": 100, "unit_price": 5.0}]
    grid1 = pgr.PricingGridReconstructionUtil.from_raw_tiers("prod-123", raw1)
    grid2 = pgr.PricingGridReconstructionUtil.from_raw_tiers("prod-123", raw2)
    merged = pgr.PricingGridReconstructionUtil.merge_grids([grid1, grid2])
    is_valid, issues = pgr.PricingGridReconstructionUtil.validate_grid(merged)
    assert is_valid is True


def test_integration_complex_pricing_scenario():
    # Three-tier pricing model typical for SaaS
    raw_tiers = [
        {"name": "starter", "min_units": 1, "max_units": 1000, "unit_price": 0.10, "flat_fee": 9.99},
        {"name": "growth", "min_units": 1001, "max_units": 10000, "unit_price": 0.07, "flat_fee": 49.99},
        {"name": "enterprise", "min_units": 10001, "max_units": None, "unit_price": 0.05, "flat_fee": 199.99},
    ]
    grid = pgr.PricingGridReconstructionUtil.from_raw_tiers("saas-prod", raw_tiers)
    is_valid, issues = pgr.PricingGridReconstructionUtil.validate_grid(grid)
    assert is_valid is True

    # Test cost at different scales
    cost_starter = grid.total_cost(500)
    cost_growth = grid.total_cost(5000)
    cost_enterprise = grid.total_cost(50000)

    assert cost_starter > 0
    assert cost_growth > cost_starter
    assert cost_enterprise > cost_growth


if __name__ == "__main__":
    test_tier_basic_creation()
    test_tier_with_flat_fee()
    test_tier_is_unlimited()
    test_tier_cost_for_units_single_unit()
    test_tier_cost_for_units_multiple()
    test_tier_cost_for_units_with_flat_fee()
    test_tier_cost_below_minimum()
    test_tier_cost_exactly_at_minimum()
    test_tier_cost_above_maximum()
    test_tier_cost_unlimited_tier()
    test_tier_metadata()

    test_grid_creation()
    test_grid_with_custom_currency()
    test_grid_sorted_tiers_order()
    test_grid_sorted_tiers_empty()
    test_grid_total_cost_single_tier()
    test_grid_total_cost_multiple_tiers()
    test_grid_total_cost_within_first_tier()
    test_grid_total_cost_zero_units()
    test_grid_total_cost_with_flat_fees()
    test_grid_tier_for_units_exact_match()
    test_grid_tier_for_units_boundary()
    test_grid_tier_for_units_no_match()
    test_grid_tier_for_units_empty_grid()
    test_grid_effective_date()

    test_util_from_raw_tiers_basic()
    test_util_from_raw_tiers_with_metadata()
    test_util_from_raw_tiers_defaults()
    test_util_from_raw_tiers_custom_currency()
    test_util_from_raw_tiers_empty()
    test_util_from_flat_price()
    test_util_from_flat_price_currency()
    test_util_merge_grids_single()
    test_util_merge_grids_multiple()
    test_util_merge_grids_empty_raises()
    test_util_merge_grids_preserves_properties()
    test_util_validate_grid_valid()
    test_util_validate_grid_empty_tiers()
    test_util_validate_grid_negative_price()
    test_util_validate_grid_max_less_than_min()
    test_util_validate_grid_overlapping_tiers()
    test_util_validate_grid_non_overlapping_boundaries()
    test_util_validate_grid_single_tier()

    test_integration_raw_to_cost()
    test_integration_flat_price_calculation()
    test_integration_merge_and_validate()
    test_integration_complex_pricing_scenario()

    print("All pricing_grid_reconstruction tests passed")
