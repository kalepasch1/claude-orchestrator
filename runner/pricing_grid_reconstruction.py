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
import common_utils

_log = _log_mod.get("pricing_grid_reconstruction")


def _tier_units_in_range(units: int, tier_min: int, tier_max: Optional[int]) -> bool:
    """Single source of truth for tier range checking."""
    if units < tier_min:
        return False
    if tier_max is not None and units > tier_max:
        return False
    return True


def _calculate_applicable_units(units: int, tier_min: int, tier_max: Optional[int]) -> int:
    """Single unified method for calculating applicable units in a tier range.

    Returns 0 if units outside range; otherwise returns applicable_units.
    """
    if not _tier_units_in_range(units, tier_min, tier_max):
        return 0
    upper = tier_max if tier_max is not None else units
    return min(units, upper) - tier_min + 1


def _build_pricing_tier_from_dict(tier_dict: Dict[str, Any]) -> 'PricingTier':
    """Single unified factory for constructing PricingTier from dict."""
    return PricingTier(
        name=tier_dict.get("name", "default"),
        min_units=int(tier_dict.get("min_units", 0)),
        max_units=int(tier_dict["max_units"]) if tier_dict.get("max_units") is not None else None,
        unit_price=float(tier_dict.get("unit_price", 0)),
        flat_fee=float(tier_dict.get("flat_fee", 0)),
        metadata=tier_dict.get("metadata", {}),
    )


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
        """Single source of truth for unlimited tier detection."""
        return self.max_units is None

    @staticmethod
    def _tier_capacity(tier: 'PricingTier') -> int:
        """Unified capacity calculation for a tier."""
        if tier.is_unlimited:
            return 0
        if tier.max_units < tier.min_units:
            return 0
        return _calculate_applicable_units(tier.max_units, tier.min_units, tier.max_units)

    def cost_for_units(self, units: int) -> float:
        """Calculate cost for units within this tier's range."""
        applicable = _calculate_applicable_units(units, self.min_units, self.max_units)
        if applicable == 0:
            return 0.0
        return self.flat_fee + (applicable * self.unit_price)

    def to_dict(self, include_metadata: bool = False) -> Dict[str, Any]:
        """Serialize tier to dict. Metadata excluded by default."""
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
    def _consume_and_cost(tier: PricingTier, remaining: int) -> Tuple[int, float]:
        """Unified method: consume units from tier and calculate cost."""
        if remaining <= 0:
            return 0, 0.0

        consumed, _ = common_utils.consume_from_tier(
            current=tier.min_units - 1,
            tier_min=tier.min_units,
            tier_max=tier.max_units,
            amount=remaining
        )
        if consumed == 0:
            cost = 0.0
        else:
            cost = tier.flat_fee + (consumed * tier.unit_price)
        return consumed, cost

    def total_cost(self, units: int) -> float:
        """Calculate total cost across all tiers for a given unit count.

        Walks tiers in ascending order, consuming units until exhausted.
        Uses unified cost calculation to eliminate duplication.
        """
        total = 0.0
        remaining = units
        for tier in self.sorted_tiers:
            if remaining <= 0:
                break
            consumed, cost = self._consume_and_cost(tier, remaining)
            total += cost
            remaining -= consumed
        return round(total, 2)

    def tier_for_units(self, units: int) -> Optional[PricingTier]:
        """Find the applicable tier for a unit count.

        Uses unified range check to eliminate duplication.
        """
        for tier in self.tiers:
            if _tier_units_in_range(units, tier.min_units, tier.max_units):
                return tier
        return None

    def to_dict(self, include_metadata: bool = False) -> Dict[str, Any]:
        """Serialize grid to dict. Tier metadata excluded by default."""
        return {
            "product_id": self.product_id,
            "currency": self.currency,
            "effective_date": self.effective_date,
            "tiers": [t.to_dict(include_metadata=include_metadata) for t in self.tiers],
        }


class PricingGridReconstructionUtil:
    """Shared utility for reconstructing pricing grids from raw data.

    Previously this logic was duplicated across multiple modules.
    All callers should now use this class. Uses unified factory and validation.
    """

    @staticmethod
    def from_raw_tiers(product_id: str, raw_tiers: List[Dict[str, Any]],
                       currency: str = "USD") -> PricingGrid:
        """Reconstruct PricingGrid from raw tier dicts using unified factory."""
        tiers = [_build_pricing_tier_from_dict(rt) for rt in raw_tiers]
        grid = PricingGrid(product_id=product_id, tiers=tiers, currency=currency)
        grid.tiers = grid.sorted_tiers
        return grid

    @staticmethod
    def from_flat_price(product_id: str, unit_price: float,
                        currency: str = "USD") -> PricingGrid:
        """Create a simple single-tier grid from a flat price."""
        tier = PricingTier(name="flat", min_units=1, max_units=None,
                           unit_price=unit_price)
        return PricingGrid(product_id=product_id, tiers=[tier], currency=currency)

    @staticmethod
    def merge_grids(grids: List[PricingGrid]) -> PricingGrid:
        """Merge multiple grids for the same product.

        Takes the grid with the most tiers as the base and normalizes via sorted_tiers.
        """
        if not grids:
            raise ValueError("cannot merge empty grid list")
        base = max(grids, key=lambda g: len(g.tiers))
        return PricingGrid(
            product_id=base.product_id,
            tiers=base.sorted_tiers,
            currency=base.currency,
            effective_date=base.effective_date,
        )

    @staticmethod
    def _validate_tier_bounds(tier: PricingTier) -> List[str]:
        """Unified tier validation: check bounds and price constraints."""
        issues = []
        if tier.unit_price < 0:
            issues.append(f"tier '{tier.name}' has negative unit_price")
        if tier.max_units is not None and tier.max_units < tier.min_units:
            issues.append(f"tier '{tier.name}' max < min")
        return issues

    @staticmethod
    def _validate_tier_overlaps(tier: PricingTier, seen_ranges: List[Tuple[str, int, Optional[int]]]) -> List[str]:
        """Unified overlap detection using centralized range check."""
        issues = []
        for prev_name, prev_min, prev_max in seen_ranges:
            if prev_max is not None and tier.min_units <= prev_max:
                issues.append(f"tier '{tier.name}' overlaps with '{prev_name}'")
        return issues

    @staticmethod
    def validate_grid(grid: PricingGrid) -> Tuple[bool, List[str]]:
        """Validate a pricing grid for consistency.

        Returns (is_valid, list_of_issues). Uses unified validation methods.
        """
        issues = []
        if not grid.tiers:
            issues.append("grid has no tiers")
            return False, issues

        seen_ranges = []
        unlimited_count = 0

        for tier in grid.tiers:
            issues.extend(PricingGridReconstructionUtil._validate_tier_bounds(tier))
            issues.extend(PricingGridReconstructionUtil._validate_tier_overlaps(tier, seen_ranges))

            if tier.is_unlimited:
                unlimited_count += 1
            seen_ranges.append((tier.name, tier.min_units, tier.max_units))

        if unlimited_count > 1:
            issues.append("grid has multiple unlimited tiers")

        return len(issues) == 0, issues
