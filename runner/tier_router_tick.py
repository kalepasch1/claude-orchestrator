#!/usr/bin/env python3
"""Periodic: log tier routing stats and subscription capacity."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def tick():
    try:
        import tier_router
        stats = tier_router.stats()
        if stats.get("total", 0) > 0:
            print(f"[tier-stats] total={stats['total']} sub={stats['sub_pct']:.0f}% "
                  f"api={stats['api_pct']:.0f}% savings=${stats['sub_cost_savings']:.2f}")
    except Exception:
        pass
    try:
        import subscription_tracker
        report = subscription_tracker.capacity_report()
        for sub in report:
            name = sub.get("name", "?")
            avail = sub.get("available", False)
            calls = sub.get("calls_last_hour", 0)
            print(f"[sub-capacity] {name}: available={avail} calls_1h={calls}")
    except Exception:
        pass

if __name__ == "__main__":
    tick()
