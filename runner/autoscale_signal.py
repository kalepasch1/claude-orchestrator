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


def throughput_signal(window_minutes=30):
    """Measure actual task throughput over the recent window.

    Returns dict with:
        tasks_completed: int — tasks finished in window
        avg_duration_seconds: float — average task duration
        tasks_per_hour: float — completion rate
        bottleneck: str — 'compute' | 'queue_empty' | 'balanced'
    """
    try:
        rows = db.sql(
            f"SELECT id, state, updated_at, finished_at "
            f"FROM tasks "
            f"WHERE state IN ('DONE', 'MERGED') "
            f"AND finished_at > now() - interval '{int(window_minutes)} minutes' "
            f"ORDER BY finished_at DESC"
        ) or []
    except Exception:
        return {"tasks_completed": 0, "avg_duration_seconds": 0, "tasks_per_hour": 0, "bottleneck": "unknown"}

    completed = len(rows)
    tasks_per_hour = completed * (60 / max(window_minutes, 1))

    # Check queue depth for bottleneck classification
    try:
        queued = db.sql("SELECT count(*) as cnt FROM tasks WHERE state = 'QUEUED'")
        queue_depth = int(queued[0]["cnt"]) if queued else 0
    except Exception:
        queue_depth = 0

    try:
        running = db.sql("SELECT count(*) as cnt FROM tasks WHERE state = 'RUNNING'")
        running_count = int(running[0]["cnt"]) if running else 0
    except Exception:
        running_count = 0

    if queue_depth > 20 and running_count > 0:
        bottleneck = "compute"  # lots queued, runners busy
    elif queue_depth < 3:
        bottleneck = "queue_empty"  # nothing to do
    else:
        bottleneck = "balanced"

    return {
        "tasks_completed": completed,
        "tasks_per_hour": round(tasks_per_hour, 1),
        "queue_depth": queue_depth,
        "running": running_count,
        "bottleneck": bottleneck,
        "window_minutes": window_minutes,
    }


def elastic_recommendation():
    """Combine demand signal and throughput signal for scaling recommendation.

    Returns: dict with action ('scale_up', 'scale_down', 'hold') and reason.
    """
    demand = run()
    throughput = throughput_signal()

    if demand["recommend"] > 0 and throughput["bottleneck"] == "compute":
        return {
            "action": "scale_up",
            "workers": demand["recommend"],
            "reason": f"High demand ({demand['weighted_demand']:.0f}) with compute bottleneck "
                      f"({throughput['queue_depth']} queued, {throughput['running']} running)",
        }

    if throughput["bottleneck"] == "queue_empty" and demand["weighted_demand"] < 5:
        return {
            "action": "scale_down",
            "workers": 0,
            "reason": f"Queue nearly empty ({throughput['queue_depth']}), low demand",
        }

    return {
        "action": "hold",
        "workers": 0,
        "reason": f"Balanced: {throughput['tasks_per_hour']}/hr throughput, "
                  f"{throughput['queue_depth']} queued",
    }
