#!/usr/bin/env python3
"""
autoscale_signal.py - capacity follows demand. When claimable work weighted by expected value exceeds
the live fleet's capacity for a sustained period, emit a "spin up another runner" signal (your Mac #2
today; a cloud box later). It NEVER starts machines itself — it tells you (or an autoscaler) to, so a
human/opsscript flips the switch. Also emits a scale-DOWN hint when the fleet is idle.

Signal = weighted_demand (claimable tasks x project ROI weight) vs fleet_ceiling (live machines x
MAX_PARALLEL). Sustained over SUSTAIN_MIN minutes -> recommend +N workers. Schedule ~every 5 min.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

SUSTAIN_MIN = int(os.environ.get("AUTOSCALE_SUSTAIN_MIN", "10"))
DEMAND_RATIO = float(os.environ.get("AUTOSCALE_DEMAND_RATIO", "2.0"))  # demand >= 2x ceiling -> scale up
_STATE = {"over_since": None}


def _claimable_weighted():
    projs = {p["id"]: p for p in (db.select("projects", {"select": "*"}) or [])}
    done = {t["slug"] for t in (db.select("tasks", {"select": "slug", "state": "in.(DONE,MERGED)"}) or [])}
    q = db.select("tasks", {"select": "project_id,deps", "state": "eq.QUEUED"}) or []
    depth = wdemand = 0
    for t in q:
        if all(d in done for d in (t.get("deps") or [])):
            depth += 1
            wdemand += float((projs.get(t.get("project_id"), {}) or {}).get("concurrency_weight") or 1)
    return depth, wdemand


def run():
    try:
        import fleet
        cap = fleet.capacity()
        ceiling = cap["ceiling"] or 0
        machines = cap["machines"]
    except Exception:
        ceiling, machines = 0, 0
    depth, wdemand = _claimable_weighted()
    over = ceiling > 0 and wdemand >= ceiling * DEMAND_RATIO
    now = time.time()
    rec = 0
    reason = ""
    if over:
        _STATE["over_since"] = _STATE["over_since"] or now
        sustained = (now - _STATE["over_since"]) >= SUSTAIN_MIN * 60
        if sustained:
            # recommend enough workers to bring demand within ~1x ceiling
            per_machine = max(1, ceiling // max(1, machines))
            need_slots = int(wdemand) - ceiling
            rec = max(1, -(-need_slots // per_machine))  # ceil division
            reason = (f"weighted demand {wdemand:.0f} >= {DEMAND_RATIO}x ceiling {ceiling} for "
                      f">{SUSTAIN_MIN}m — add ~{rec} runner(s) (e.g. start Mac #2)")
    else:
        _STATE["over_since"] = None
        if ceiling > 0 and machines > 1 and wdemand < ceiling * 0.25:
            reason = f"fleet idle (demand {wdemand:.0f} << ceiling {ceiling}) — a runner could stand down"

    db.insert("autoscale_signals", {"queue_depth": depth, "weighted_demand": wdemand,
              "fleet_ceiling": ceiling, "recommend_workers": rec, "reason": reason or "within capacity"})
    if rec > 0:
        db.insert("approvals", {"project": "PORTFOLIO", "kind": "self",
                  "title": f"Scale up: add ~{rec} runner(s)", "why": reason,
                  "value": "Demand exceeds fleet capacity — more workers = near-linear throughput.",
                  "risk": "Start your second Mac (or a cloud box); atomic claim prevents collisions.",
                  "command": ""})
    print(f"autoscale_signal: depth={depth} wdemand={wdemand:.0f} ceiling={ceiling} "
          f"machines={machines} recommend={rec} :: {reason or 'within capacity'}")
    return {"depth": depth, "weighted_demand": wdemand, "ceiling": ceiling, "recommend": rec}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
