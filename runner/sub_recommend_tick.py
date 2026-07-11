#!/usr/bin/env python3
"""Periodic: analyze API spend and recommend subscriptions when ROI-positive."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def tick():
    try:
        import subscription_tracker
        recs = subscription_tracker.recommend_subscriptions()
        for r in recs:
            print(f"[sub-recommend] {r['vendor']}/{r['tier']}: "
                  f"${r['monthly_cost']}/mo saves ${r.get('monthly_savings',0):.0f}/mo "
                  f"(ROI {r.get('roi_pct',0):.0f}%)")
    except Exception:
        pass
    try:
        import fleet_topology
        reco = fleet_topology.recommend_topology()
        for r in reco.get("recommendations", [])[:3]:
            print(f"[fleet-recommend] {r['action']}: {r.get('rationale','')[:100]}")
    except Exception:
        pass

if __name__ == "__main__":
    tick()
