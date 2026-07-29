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

    @staticmethod
    def _tier_capacity(tier: 'PricingTier') -> int:
        """Calculate capacity (max number of units) this tier can hold.

        Returns:
            - 0 for unlimited tiers (max_units=None)
            - max - min + 1 for limited tiers
            - 0 for invalid tiers (max < min)
        """
        if tier.max_units is None:
            return 0
        if tier.max_units < tier.min_units:
            return 0
        return tier.max_units - tier.min_units + 1

    def cost_for_units(self, units: int) -> float:
        """Calculate cost for a given number of units within this tier.

        Only counts units that fall within [min_units, max_units].
        Returns 0 if units are outside the valid range.
        Otherwise returns flat_fee + (applicable_units * unit_price).
        """
        if units < self.min_units or (self.max_units is not None and units > self.max_units):
            return 0.0
        upper = self.max_units if self.max_units is not None else units
        applicable = min(units, upper) - self.min_units + 1
        return self.flat_fee + (applicable * self.unit_price)

    def to_dict(self, include_metadata: bool = False) -> Dict[str, Any]:
        """Serialize tier to dict. Metadata (including template IDs) excluded by default.

        Args:
            include_metadata: If True, include metadata in serialization.
                             Template IDs and other sensitive config must be
                             explicitly requested to prevent cross-grid leakage.

        Returns:
            dict with name, min_units, max_units, unit_price, flat_fee.
            Metadata is only included if include_metadata=True.
        """
        result = {
            "name": self.name,
            "min_units": self.min_units,
            "max_units": self.max_units,
            "unit_price": self.unit_price,
            "flat_fee": self.flat_fee,
        }
        if include_metadata:
            result["metadata"] = self.metadata
        return result


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

    @staticmethod
    def _consume_tier_units(tier: PricingTier, remaining: int) -> Tuple[int, float]:
        """Consume units from a tier and return (units_consumed, cost).

        Args:
            tier: The pricing tier to consume from
            remaining: Number of units available to consume

        Returns:
            Tuple of (units_consumed, cost) where:
            - units_consumed is the number of units actually consumed
            - cost includes flat fee (if any) plus per-unit charges
        """
        if remaining <= 0:
            return 0, 0.0

        if tier.max_units is None:
            # Unlimited tier: consume all remaining
            consumed = remaining
        else:
            # Limited tier: consume up to capacity
            capacity = tier.max_units - tier.min_units + 1
            consumed = min(remaining, capacity)

        cost = tier.flat_fee + (consumed * tier.unit_price)
        return consumed, cost

    def total_cost(self, units: int) -> float:
        """Calculate total cost across all tiers for a given unit count.

        Walks tiers in ascending order, consuming units until exhausted.
        """
        total = 0.0
        remaining = units
        for tier in self.sorted_tiers:
            if remaining <= 0:
                break
            consumed, cost = self._consume_tier_units(tier, remaining)
            total += cost
            remaining -= consumed
        return round(total, 2)

    def tier_for_units(self, units: int) -> Optional[PricingTier]:
        """Find the applicable tier for a unit count."""
        for tier in self.tiers:
            if tier.min_units <= units and (tier.max_units is None or units <= tier.max_units):
                return tier
        return None

    def to_dict(self, include_metadata: bool = False) -> Dict[str, Any]:
        """Serialize grid to dict. Metadata (including template IDs) excluded by default.

        Args:
            include_metadata: If True, include tier metadata in serialization.
                             Template IDs and other sensitive config must be
                             explicitly requested to prevent cross-grid leakage.

        Returns:
            dict with product_id, currency, effective_date, and tiers list.
            Tier metadata is only included if include_metadata=True.
        """
        return {
            "product_id": self.product_id,
            "currency": self.currency,
            "effective_date": self.effective_date,
            "tiers": [t.to_dict(include_metadata=include_metadata) for t in self.tiers],
        }


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
