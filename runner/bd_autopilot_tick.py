#!/usr/bin/env python3
"""
bd_autopilot_tick.py — recurring driver for the autonomous BD layer + portfolio budget brain.
Registered as the 'bd_autopilot' loop type. Each tick:
  1. triggers Smarter's gated outreach tick for each app (real sends happen there; the outreach_allowed
     gate + suppression + approvals are enforced inside),
  2. rebalances portfolio budget by momentum and trips the CAC circuit breaker.
All fail-soft. NOTE: sends only fire for contacts/campaigns a human has explicitly enabled — the
global switch ships 'off'.
"""
import os, sys, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

APPS = [a.strip() for a in os.environ.get("BD_AUTOPILOT_APPS", "smarter,apparently,tomorrow").split(",") if a.strip()]


def _post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                headers={"Content-Type": "application/json"}, method="POST")
    return urllib.request.urlopen(req, timeout=15).read()


def run():
    # 1) drive Smarter's gated outreach tick per app (no-op if endpoint unset)
    url = os.environ.get("SMARTER_AUTOPILOT_URL")  # e.g. https://<smarter-host>/api/growth/autopilot
    if url:
        for app in APPS:
            try:
                _post(url, {"action": "tick", "app": app})
            except Exception as e:
                print(f"bd_autopilot tick error {app}: {e}")
    else:
        print("bd_autopilot: SMARTER_AUTOPILOT_URL unset; skipping outreach tick")

    # 2) portfolio budget brain: reallocate by momentum, trip circuit breakers
    try:
        total = float(os.environ.get("PORTFOLIO_WEEKLY_BUDGET", "0"))
        if total > 0:
            db.rpc("rebalance_budget", {"p_total": total})
            db.rpc("check_cac_circuit", {"p_window": "7 days", "p_min_spend": 100})
    except Exception as e:
        print(f"bd_autopilot budget error: {e}")


if __name__ == "__main__":
    run()
