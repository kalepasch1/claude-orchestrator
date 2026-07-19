"""
cx_calibration_budget.py

Allocates calibration budget across CX verticals based on
outcome signal quality and model-drift indicators.

When a vertical's prediction accuracy drops below threshold,
its calibration budget increases so the calibrator runs more
frequently on that vertical's data.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class VerticalSignal:
    vertical: str
    accuracy: float        # 0..1, recent prediction accuracy
    sample_count: int      # number of recent observations
    drift_score: float     # 0..1, higher = more drift detected


@dataclass
class BudgetAllocation:
    vertical: str
    budget_pct: float      # percentage of total calibration budget
    priority: int          # 1 = highest
    reason: str


@dataclass
class CalibrationBudgetPlan:
    total_budget_usd: float
    allocations: List[BudgetAllocation]
    verticals_needing_calibration: int
    verticals_stable: int


ACCURACY_THRESHOLD = 0.85
DRIFT_THRESHOLD = 0.3
MIN_SAMPLES = 10


def score_urgency(signal: VerticalSignal) -> float:
    """Higher urgency → more calibration budget needed."""
    accuracy_gap = max(0, ACCURACY_THRESHOLD - signal.accuracy)
    drift_factor = max(0, signal.drift_score - DRIFT_THRESHOLD) if signal.drift_score > DRIFT_THRESHOLD else 0
    sample_penalty = 1.0 if signal.sample_count < MIN_SAMPLES else 0.0

    return accuracy_gap * 3.0 + drift_factor * 2.0 + sample_penalty * 0.5


def allocate_calibration_budget(
    signals: List[VerticalSignal],
    total_budget_usd: float = 100.0,
) -> CalibrationBudgetPlan:
    """
    Distribute calibration budget across verticals proportional
    to urgency. Stable verticals get zero allocation.
    """
    scored = [(s, score_urgency(s)) for s in signals]
    needing = [(s, u) for s, u in scored if u > 0]
    stable = [(s, u) for s, u in scored if u == 0]

    if not needing:
        return CalibrationBudgetPlan(
            total_budget_usd=total_budget_usd,
            allocations=[],
            verticals_needing_calibration=0,
            verticals_stable=len(stable),
        )

    total_urgency = sum(u for _, u in needing)
    allocations: List[BudgetAllocation] = []

    for signal, urgency in sorted(needing, key=lambda x: -x[1]):
        pct = urgency / total_urgency
        reasons = []
        if signal.accuracy < ACCURACY_THRESHOLD:
            reasons.append(f"accuracy {signal.accuracy:.2f} < {ACCURACY_THRESHOLD}")
        if signal.drift_score > DRIFT_THRESHOLD:
            reasons.append(f"drift {signal.drift_score:.2f} > {DRIFT_THRESHOLD}")
        if signal.sample_count < MIN_SAMPLES:
            reasons.append(f"low samples ({signal.sample_count})")

        allocations.append(BudgetAllocation(
            vertical=signal.vertical,
            budget_pct=round(pct * 100, 1),
            priority=len(allocations) + 1,
            reason="; ".join(reasons) or "general recalibration",
        ))

    return CalibrationBudgetPlan(
        total_budget_usd=total_budget_usd,
        allocations=allocations,
        verticals_needing_calibration=len(needing),
        verticals_stable=len(stable),
    )


def should_trigger_calibration(signal: VerticalSignal) -> bool:
    """Quick check: does this vertical need calibration right now?"""
    return score_urgency(signal) > 0
