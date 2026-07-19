#!/usr/bin/env python3
"""
portfolio_ab_analytics.py - cross-portfolio A/B test aggregation.

Query endpoint that aggregates A/B test results across all apps:
  - Groups by tactic (experiment type / hypothesis)
  - Shows lift and p-value per app
  - Computes portfolio-wide average lift

Usage:
    python3 portfolio_ab_analytics.py              # print JSON summary
    python3 portfolio_ab_analytics.py --tactic X   # filter by tactic
"""
import os, sys, json, math
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def _p_value(control_n, control_rate, variant_n, variant_rate):
    """Approximate two-proportion z-test p-value (two-tailed)."""
    if control_n < 1 or variant_n < 1:
        return 1.0
    pooled = (control_rate * control_n + variant_rate * variant_n) / (control_n + variant_n)
    if pooled <= 0 or pooled >= 1:
        return 1.0
    se = math.sqrt(pooled * (1 - pooled) * (1.0 / control_n + 1.0 / variant_n))
    if se == 0:
        return 1.0
    z = abs(variant_rate - control_rate) / se
    # Approximate normal CDF via Abramowitz & Stegun
    t = 1.0 / (1.0 + 0.2316419 * z)
    d = 0.3989422804014327 * math.exp(-z * z / 2.0)
    p_one = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
    return min(1.0, 2.0 * p_one)


def _lift(control_rate, variant_rate):
    """Relative lift: (variant - control) / control."""
    if control_rate <= 0:
        return 0.0
    return (variant_rate - control_rate) / control_rate


def aggregate_ab_results(tactic_filter=None):
    """Aggregate A/B experiment results across all projects.

    Returns a dict keyed by tactic, each containing per-app stats and a
    portfolio-wide average lift.
    """
    experiments = db.select("experiments", {"select": "*"}) or []
    outcomes = db.select("outcomes", {"select": "*", "order": "created_at.desc", "limit": "2000"}) or []

    # Index outcomes by experiment_id
    outcomes_by_exp = defaultdict(list)
    for o in outcomes:
        eid = o.get("experiment_id") or o.get("exp_id")
        if eid:
            outcomes_by_exp[eid].append(o)

    # Group experiments by tactic
    by_tactic = defaultdict(list)
    for exp in experiments:
        tactic = exp.get("tactic") or exp.get("hypothesis_type") or "unknown"
        if tactic_filter and tactic != tactic_filter:
            continue
        project = exp.get("project") or exp.get("app") or "unknown"
        eid = exp.get("id")

        exp_outcomes = outcomes_by_exp.get(eid, [])
        control = [o for o in exp_outcomes if o.get("variant") == "control" or o.get("is_control")]
        variant = [o for o in exp_outcomes if o.get("variant") != "control" and not o.get("is_control")]

        control_n = len(control) or 1
        variant_n = len(variant) or 1
        control_rate = sum(1 for o in control if o.get("success")) / control_n
        variant_rate = sum(1 for o in variant if o.get("success")) / variant_n

        lift = _lift(control_rate, variant_rate)
        p = _p_value(control_n, control_rate, variant_n, variant_rate)

        by_tactic[tactic].append({
            "app": project,
            "experiment_id": eid,
            "control_n": control_n,
            "variant_n": variant_n,
            "control_rate": round(control_rate, 4),
            "variant_rate": round(variant_rate, 4),
            "lift": round(lift, 4),
            "p_value": round(p, 4),
            "status": exp.get("status", "unknown"),
        })

    # Compute portfolio-wide averages per tactic
    result = {}
    for tactic, entries in by_tactic.items():
        lifts = [e["lift"] for e in entries if e["control_n"] > 0]
        avg_lift = sum(lifts) / len(lifts) if lifts else 0.0
        result[tactic] = {
            "per_app": entries,
            "portfolio_avg_lift": round(avg_lift, 4),
            "app_count": len(entries),
        }

    return result


def run(tactic_filter=None):
    results = aggregate_ab_results(tactic_filter)
    print(json.dumps(results, indent=2, default=str))
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Cross-portfolio A/B analytics")
    parser.add_argument("--tactic", default=None, help="Filter by tactic name")
    args = parser.parse_args()
    run(args.tactic)
