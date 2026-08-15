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
import os, re, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

FLEET_TTL = int(os.environ.get("FLEET_TTL_S", "180"))
PER_MACHINE_MAX = int(os.environ.get("MAX_PARALLEL", "4"))


def _physical_host(name):
    raw = str(name or "")
    marker = " lane "
    return raw.split(marker, 1)[0] if marker in raw else raw


def _is_lane(name):
    return " lane " in str(name or "")


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
    # The table accumulates rows across process restarts. Always request the
    # freshest bounded window or an arbitrary PostgREST page can contain mostly
    # dead runners and make a busy fleet look empty.
    rows = db.select("runner_heartbeats", {
        "select": "*", "order": "last_seen.desc", "limit": str(STATUS_SCAN_LIMIT),
    }) or []
    rows = _live(rows)
    # Collapse logical lane heartbeats back to physical machines. The base
    # scheduler heartbeat is authoritative when it is still current; lane rows
    # are visibility records, not extra hardware.
    groups = {}
    for r in rows:
        h = _physical_host(r.get("hostname") or r.get("runner_id"))
        groups.setdefault(h, []).append(r)
    live = []
    for h, items in groups.items():
        real = [r for r in items if not _is_lane(r.get("hostname") or r.get("runner_id"))]
        candidates = real or items
        freshest = max(candidates, key=lambda r: r.get("last_seen") or "")
        source = freshest
        schedulers = [
            r for r in candidates if str(r.get("runner_id") or "").endswith("-scheduler")
        ]
        if schedulers:
            scheduler = max(schedulers, key=lambda r: r.get("last_seen") or "")
            try:
                sched_at = datetime.datetime.fromisoformat(
                    str(scheduler.get("last_seen")).replace("Z", "+00:00")
                )
                fresh_at = datetime.datetime.fromisoformat(
                    str(freshest.get("last_seen")).replace("Z", "+00:00")
                )
                grace = int(os.environ.get("ORCH_SCHEDULER_HEARTBEAT_GRACE_S", "60"))
                if (fresh_at - sched_at).total_seconds() <= grace:
                    source = scheduler
            except Exception:
                pass
        nr = dict(source)
        nr["hostname"] = h
        contracts = {}
        for item in items:
            contract = (item.get("code_sha") or "unknown", item.get("contract_hash") or "unknown")
            contracts[contract] = contracts.get(contract, 0) + 1
        dominant, _count = max(contracts.items(), key=lambda pair: pair[1])
        nr["code_sha"], nr["contract_hash"] = dominant
        nr["contract_variants"] = len(contracts)
        nr["contract_compatible"] = len(contracts) == 1 and dominant[1] != "unknown"
        if not real:
            nr["active_tasks"] = sum(int(r.get("active_tasks") or 0) for r in items)
        live.append(nr)
    return {
        "machines_live": len(live),
        "machines": [{"host": r.get("hostname"), "runner": r.get("runner_id"),
                      "active": r.get("active_tasks"), "last_seen": r.get("last_seen"),
                      "code_sha": r.get("code_sha"), "contract_hash": r.get("contract_hash"),
                      "contract_variants": r.get("contract_variants"),
                      "contract_compatible": r.get("contract_compatible")} for r in live],
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
