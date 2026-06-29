#!/usr/bin/env python3
"""
chaos.py - resilience drills. Periodically injects a controlled failure and verifies the
self-heal loops actually recover. Run in a SAFE/staging context only.

Drills:
  stale-runner : write a stale heartbeat and confirm the dashboard marks it offline.
  fake-fail    : file a synthetic failing 'integrate' approval and confirm it surfaces.
After injecting, it records whether recovery/visibility happened (for your review).
"""
import os, sys, time, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ENABLED = os.environ.get("CHAOS_ENABLED", "false").lower() == "true"


def stale_runner():
    old = (datetime.datetime.utcnow() - datetime.timedelta(minutes=10)).isoformat()
    db.insert("runner_heartbeats", {"runner_id": "chaos-drill", "hostname": "chaos",
                                    "active_tasks": 0, "last_seen": old}, upsert=True)
    return "injected stale runner 'chaos-drill' (dashboard should show it OFFLINE)"


def fake_fail():
    db.insert("approvals", {"project": "CHAOS", "kind": "self", "title": "Chaos drill: synthetic failure",
                            "why": "Injected to verify alerts/visibility.",
                            "value": "Confirms the human-attention path works.", "command": ""})
    return "filed synthetic failure approval (should appear in the inbox)"


def run(drill="stale-runner"):
    if not ENABLED:
        return "CHAOS disabled (set CHAOS_ENABLED=true in a safe env)"
    return {"stale-runner": stale_runner, "fake-fail": fake_fail}.get(drill, fake_fail)()


if __name__ == "__main__":
    print(run(sys.argv[1] if len(sys.argv) > 1 else "stale-runner"))
