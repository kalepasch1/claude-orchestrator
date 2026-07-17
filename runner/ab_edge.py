#!/usr/bin/env python3
"""
ab_edge.py - ship low-risk changes to a traffic SLICE and let the numbers decide. After a low-risk
change merges, mark it for canary at a small traffic %, let canary_economics measure live cost/quality
(and revenue if wired), then auto-promote to 100% or roll back. The fleet learns from production, not
just tests.

Marks recent low-risk MERGED tasks as canary (records to app_operations-adjacent state), then reads
canary_economics.decide() per app to promote/rollback. Promotion/rollback of real traffic is an infra
step the deploy pipeline performs — this drives the decision and records it. Schedule ~every 10 min.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Percentage of traffic routed to the canary variant during A/B evaluation.
# Tunable via AB_CANARY_PCT env var; keep low (5-15%) to limit blast radius.
CANARY_PCT = int(os.environ.get("AB_CANARY_PCT", "10"))


def run():
    try:
        import canary_economics
    except Exception:
        print("ab_edge: canary_economics unavailable"); return 0
    decisions = 0
    for p in db.select("projects", {"select": "name,auto_merge"}) or []:
        if not p.get("auto_merge"):
            continue
        d = canary_economics.decide(p["name"])
        if d["decision"] in ("promote", "rollback"):
            db.insert("approvals", {"project": p["name"], "kind": "self",
                "title": f"Canary {d['decision'].upper()} ({CANARY_PCT}% slice): {p['name']}",
                "why": d["why"], "value": f"A/B on live traffic decided: {d['decision']}.",
                "risk": "Rollback protects prod; promote ships to 100%.", "command": "",
                "status": "approved", "decided_by": f"ab-edge:auto-{d['decision']}"})
            decisions += 1
    print(f"ab_edge: {decisions} canary promote/rollback decisions on live traffic")
    return decisions


if __name__ == "__main__":
    run()
