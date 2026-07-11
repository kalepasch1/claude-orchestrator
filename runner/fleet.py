#!/usr/bin/env python3
"""
fleet.py - multi-machine awareness. The runner's singleton lock is PER-MACHINE (one runner per
box), but coordination is in Supabase: db.claim_task() ends every claim with an atomic optimistic
PATCH (state=QUEUED -> RUNNING), so any number of machines can pull from the same queue WITHOUT
double-claiming. That means scale-out = "run the same runner on another box pointed at the same
Supabase". No central coordinator needed; no code changes to add a worker.

This module just gives visibility + capacity math across the fleet:
  status()   -> live machines (fresh heartbeat), their active task counts, total capacity
  capacity() -> aggregate concurrent slots currently in use vs the fleet ceiling
Machines are considered LIVE if their heartbeat is within FLEET_TTL seconds.
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

FLEET_TTL = int(os.environ.get("FLEET_TTL_S", "180"))
PER_MACHINE_MAX = int(os.environ.get("MAX_PARALLEL", "4"))


def _live(rows):
    now = datetime.datetime.now(datetime.timezone.utc)
    live = []
    for r in rows:
        ls = r.get("last_seen")
        if not ls:
            continue
        try:
            t = datetime.datetime.fromisoformat(ls.replace("Z", "+00:00"))
        except Exception:
            continue
        if (now - t).total_seconds() <= FLEET_TTL:
            live.append(r)
    return live


STATUS_SCAN_LIMIT = int(os.environ.get("ORCH_FLEET_STATUS_SCAN_LIMIT", "500"))


def status():
    # 2026-07-11: runner_heartbeats accumulates one row PER RUNNER RESTART (each restart gets a
    # new PID-based runner_id, and heartbeat() upserts on runner_id -- so restarts, not lane
    # churn, are what grow this table over time). An unordered, unbounded select() could return
    # an arbitrary slice dominated by long-dead rows, making _live() find almost nothing even
    # when the fleet has dozens of genuinely live lanes -- this made fleet.capacity() report
    # near-empty utilization while the real fleet was near-saturated. Order by last_seen DESC so
    # the freshest rows are always the ones fetched, regardless of total table size/history.
    rows = db.select("runner_heartbeats", {
        "select": "*", "order": "last_seen.desc", "limit": str(STATUS_SCAN_LIMIT),
    }) or []
    # collapse to the freshest heartbeat per hostname (a machine may have restarted -> new pid)
    by_host = {}
    for r in rows:
        h = r.get("hostname") or r.get("runner_id")
        cur = by_host.get(h)
        if not cur or (r.get("last_seen") or "") > (cur.get("last_seen") or ""):
            by_host[h] = r
    live = _live(list(by_host.values()))
    return {
        "machines_live": len(live),
        "machines": [{"host": r.get("hostname"), "runner": r.get("runner_id"),
                      "active": r.get("active_tasks"), "last_seen": r.get("last_seen")} for r in live],
        "fleet_ceiling": len(live) * PER_MACHINE_MAX,
        "in_use": sum(int(r.get("active_tasks") or 0) for r in live),
        "per_machine_max": PER_MACHINE_MAX,
    }


def capacity():
    s = status()
    return {"in_use": s["in_use"], "ceiling": s["fleet_ceiling"],
            "free": max(0, s["fleet_ceiling"] - s["in_use"]), "machines": s["machines_live"]}


if __name__ == "__main__":
    import json
    print(json.dumps(status(), indent=2, default=str))
