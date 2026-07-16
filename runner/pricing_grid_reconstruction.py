#!/usr/bin/env python3
"""
pricing_grid_reconstruction.py — shared utility for pricing grid reconstruction.

Consolidates previously duplicated pricing grid reconstruction logic into a
single PricingGridReconstructionUtil class. All callers should use this module
instead of inline reconstruction logic.

This addresses the duplication identified in duplication_analysis.md.
"""
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("pricing_grid_reconstruction")


@dataclass
class PricingTier:
    """A single tier in a pricing grid."""
    name: str
    min_units: int
    max_units: Optional[int]  # None = unlimited
    unit_price: float
    flat_fee: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_unlimited(self) -> bool:
        return self.max_units is None

    def cost_for_units(self, units: int) -> float:
        """Calculate cost for a given number of units within this tier.

        Only counts units that fall within [min_units, max_units].
        Returns flat_fee + (applicable_units * unit_price).
        """
        if units < self.min_units:
            return 0.0
        upper = self.max_units if self.max_units is not None else units
        applicable = min(units, upper) - self.min_units + 1
        return self.flat_fee + (applicable * self.unit_price)


@dataclass
class PricingGrid:
    """Reconstructed pricing grid with tiered pricing."""
    product_id: str
    tiers: List[PricingTier] = field(default_factory=list)
    currency: str = "USD"
    effective_date: Optional[str] = None

    @property
    def sorted_tiers(self) -> List[PricingTier]:
        """Tiers sorted by min_units ascending."""
        return sorted(self.tiers, key=lambda t: t.min_units)

    def total_cost(self, units: int) -> float:
        """Calculate total cost across all tiers for a given unit count.

        Walks tiers in ascending order, consuming units until exhausted.
        """
        total = 0.0
        remaining = units
        for tier in self.sorted_tiers:
            if remaining <= 0:
                break
            tier_capacity = (tier.max_units - tier.min_units + 1) if tier.max_units is not None else remaining
            applicable = min(remaining, tier_capacity)
            total += tier.flat_fee + (applicable * tier.unit_price)
            remaining -= applicable
        return round(total, 2)

    def tier_for_units(self, units: int) -> Optional[PricingTier]:
        """Find the applicable tier for a unit count."""
        for tier in self.tiers:
            if tier.min_units <= units and (tier.max_units is None or units <= tier.max_units):
                return tier
        return None


class PricingGridReconstructionUtil:
    """Shared utility for reconstructing pricing grids from raw data.

    Previously this logic was duplicated across multiple modules.
    All callers should now use this class.
    """

    @staticmethod
    def from_raw_tiers(product_id: str, raw_tiers: List[Dict[str, Any]],
                       currency: str = "USD") -> PricingGrid:
        """Reconstruct a PricingGrid from raw tier data (e.g., from API/DB).

        Each dict in raw_tiers should have:
            name, min_units, max_units (or None), unit_price, flat_fee (optional)
        """
        tiers = []
        for rt in raw_tiers:
            tiers.append(PricingTier(
                name=rt.get("name", "default"),
                min_units=int(rt.get("min_units", 0)),
                max_units=int(rt["max_units"]) if rt.get("max_units") is not None else None,
                unit_price=float(rt.get("unit_price", 0)),
                flat_fee=float(rt.get("flat_fee", 0)),
                metadata=rt.get("metadata", {}),
            ))
        grid = PricingGrid(product_id=product_id, tiers=tiers, currency=currency)
        grid.tiers = grid.sorted_tiers  # normalize order on construction
        return grid

    @staticmethod
    def from_flat_price(product_id: str, unit_price: float,
                        currency: str = "USD") -> PricingGrid:
        """Create a simple single-tier grid from a flat price."""
        return PricingGrid(
            product_id=product_id,
            tiers=[PricingTier(name="flat", min_units=1, max_units=None,
                               unit_price=unit_price)],
            currency=currency,
        )

    @staticmethod
    def merge_grids(grids: List[PricingGrid]) -> PricingGrid:
        """Merge multiple grids for the same product (e.g., from different sources).

        Takes the grid with the most tiers as the base. Uses sorted_tiers
        to ensure consistent ordering in the result.
        """
        if not grids:
            raise ValueError("cannot merge empty grid list")
        base = max(grids, key=lambda g: len(g.tiers))
        merged = PricingGrid(
            product_id=base.product_id,
            tiers=base.sorted_tiers,
            currency=base.currency,
            effective_date=base.effective_date,
        )
        return merged

    @staticmethod
    def validate_grid(grid: PricingGrid) -> Tuple[bool, List[str]]:
        """Validate a pricing grid for consistency.

        Returns (is_valid, list_of_issues).
        """
        issues = []
        if not grid.tiers:
            issues.append("grid has no tiers")
        seen_ranges = []
        for tier in grid.tiers:
            if tier.unit_price < 0:
                issues.append(f"tier '{tier.name}' has negative unit_price")
            if tier.max_units is not None and tier.max_units < tier.min_units:
                issues.append(f"tier '{tier.name}' max < min")
            for prev_name, prev_min, prev_max in seen_ranges:
                if prev_max is not None and tier.min_units <= prev_max:
                    issues.append(f"tier '{tier.name}' overlaps with '{prev_name}'")
            seen_ranges.append((tier.name, tier.min_units, tier.max_units))
        return len(issues) == 0, issues
