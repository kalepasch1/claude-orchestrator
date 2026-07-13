#!/usr/bin/env python3
"""
cx_calibration_budget.py - Calibration-aware budget advisor.

Reads committee_scoreboard for Brier scores across committees, computes a
weighted Brier score, determines a budget adjustment factor, and writes an
advisory control so downstream runners can scale their token/compute budgets
based on overall system calibration quality.

Well-calibrated system (low Brier) -> tighter budgets (save tokens).
Poorly-calibrated system (high Brier) -> looser budgets (allow exploration).
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Floor on budget multiplier — never go below 60% of default budget
MIN_BUDGET = 0.6


def _adjustment_for_brier(weighted_brier):
    """Convert weighted Brier score to a budget adjustment multiplier.

    Brier score ranges 0 (perfect) to 1 (worst).
    - Brier <= 0.1  -> multiplier = MIN_BUDGET  (well calibrated, tighten budget)
    - Brier >= 0.4  -> multiplier = 1.5         (poorly calibrated, widen budget)
    - Linear interpolation in between.
    """
    if weighted_brier is None:
        return 1.0
    low, high = 0.1, 0.4
    mult_low, mult_high = MIN_BUDGET, 1.5
    if weighted_brier <= low:
        return mult_low
    if weighted_brier >= high:
        return mult_high
    # Linear interpolation
    t = (weighted_brier - low) / (high - low)
    return round(mult_low + t * (mult_high - mult_low), 3)


def run():
    """Main entry point. Read scoreboard, compute weighted Brier, write advisory."""
    rows = db.select("committee_scoreboard", {
        "select": "committee,calls,brier",
        "entity_type": "eq.committee",
    }) or []

    with_brier = [r for r in rows if r.get("brier") is not None and (r.get("calls") or 0) >= 3]
    if not with_brier:
        print("cx_calibration_budget: no scoreboard data with Brier scores, skipping")
        return {"adjustment": 1.0, "reason": "no data"}

    # Weighted Brier: weight each committee by its call count
    total_calls = sum(r.get("calls", 0) for r in with_brier)
    if total_calls == 0:
        print("cx_calibration_budget: zero total calls, skipping")
        return {"adjustment": 1.0, "reason": "zero calls"}

    weighted_brier = sum(
        float(r["brier"]) * (r.get("calls", 0) / total_calls)
        for r in with_brier
    )
    weighted_brier = round(weighted_brier, 4)

    adjustment = _adjustment_for_brier(weighted_brier)

    advisory = {
        "weighted_brier": weighted_brier,
        "adjustment": adjustment,
        "committees_sampled": len(with_brier),
        "total_calls": total_calls,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # Write advisory to controls table
    try:
        db.upsert("controls", {
            "key": "calibration_budget_advisory",
            "value": json.dumps(advisory, default=str),
        })
    except Exception:
        pass

    print(f"cx_calibration_budget: weighted_brier={weighted_brier}, adjustment={adjustment}, "
          f"committees={len(with_brier)}, calls={total_calls}")
    return advisory


if __name__ == "__main__":
    run()
