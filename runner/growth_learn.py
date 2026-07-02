#!/usr/bin/env python3
"""
growth_learn.py — the continuous-learning brain tick for the Growth OS.

Registered as the 'growth_learn' loop type. Each run folds the latest evidence back into the system:
  - sync_ad_performance()      pull external ad spend/conversions into the event bus + budget
  - compute_growth_momentum()  re-rank apps on fresh data
  - evaluate_growth_arms()     confidence-gate: crown winners / kill losers
  - refresh_world_model()      update portfolio priors that seed new experiments
  - auto_rollback_check()      pause any campaign whose health dropped (safety)
  - compounding_dividend()     propose proven wins into apps that lack them
  - plan_operator_week()       (re)book the human's highest-value week
  - counterfactual_value()     log the incremental value the system created
Everything is fail-soft and gated; nothing here sends or spends on its own.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

STEPS = [
    ("sync_ad_performance",     {}),
    ("compute_growth_momentum", {}),
    ("evaluate_growth_arms",    {"p_min_impressions": 200}),
    ("refresh_world_model",     {}),
    ("auto_rollback_check",     {"p_min_sent": 20, "p_health_floor": 0.7}),
    ("compounding_dividend",    {}),
    ("plan_operator_week",      {}),
]


def run():
    results = {}
    for fn, args in STEPS:
        try:
            db.rpc(fn, args)
            results[fn] = "ok"
        except Exception as e:
            results[fn] = f"err: {e}"
            print(f"growth_learn {fn}: {e}")
    # log incremental value created (counterfactual) as a resource event for the oversight dashboard
    try:
        val = db.rpc("counterfactual_value", {})
        db.insert("resource_events", {"kind": "growth_counterfactual_value",
                                      "value": (val if isinstance(val, (int, float)) else None),
                                      "detail": "incremental conversions vs baseline"})
    except Exception as e:
        print(f"growth_learn counterfactual: {e}")
    print("growth_learn tick:", results)
    return results


if __name__ == "__main__":
    run()
