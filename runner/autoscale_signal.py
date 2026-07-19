#!/usr/bin/env python3
"""
autoscale_signal.py - capacity follows demand. When claimable work weighted by expected value exceeds
the live fleet's capacity for a sustained period, emit a "spin up another runner" signal (your Mac #2
today; a cloud box later). It NEVER starts machines itself — it tells you (or an autoscaler) to, so a
human/opsscript flips the switch. Also emits a scale-DOWN hint when the fleet is idle.

Signal = weighted_demand (claimable tasks x project ROI weight) vs fleet_ceiling (live machines x
MAX_PARALLEL). Sustained over SUSTAIN_MIN minutes -> recommend +N workers. Schedule ~every 5 min.

v2 additions:
- Cooldown tracking: after emitting a scale-up signal, suppress further signals for
  COOLDOWN_MIN minutes to avoid flapping.
- Hysteresis: scale-down requires demand to stay below LOW_RATIO for SUSTAIN_MIN
  (same sustain window as scale-up) to prevent oscillation.
- Stats: thread-safe stats() for observability.
"""
import os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

SUSTAIN_MIN = int(os.environ.get("AUTOSCALE_SUSTAIN_MIN", "10"))
DEMAND_RATIO = float(os.environ.get("AUTOSCALE_DEMAND_RATIO", "2.0"))
COOLDOWN_MIN = int(os.environ.get("AUTOSCALE_COOLDOWN_MIN", "30"))
LOW_RATIO = float(os.environ.get("AUTOSCALE_LOW_RATIO", "0.25"))

_lock = threading.Lock()
_STATE = {"over_since": None, "under_since": None, "last_scale_up_at": 0,
          "signals_emitted": 0, "cooldowns_suppressed": 0}


def stats():
    """Return a snapshot of autoscale state for observability."""
    with _lock:
        return dict(_STATE)


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
    under = ceiling > 0 and machines > 1 and wdemand < ceiling * LOW_RATIO
    now = time.time()
    rec = 0
    reason = ""

    with _lock:
        # --- Scale UP with cooldown ---
        if over:
            _STATE["over_since"] = _STATE["over_since"] or now
            _STATE["under_since"] = None
            sustained = (now - _STATE["over_since"]) >= SUSTAIN_MIN * 60
            in_cooldown = (now - _STATE["last_scale_up_at"]) < COOLDOWN_MIN * 60
            if sustained and not in_cooldown:
                per_machine = max(1, ceiling // max(1, machines))
                need_slots = int(wdemand) - ceiling
                rec = max(1, -(-need_slots // per_machine))
                reason = (f"weighted demand {wdemand:.0f} >= {DEMAND_RATIO}x ceiling {ceiling} for "
                          f">{SUSTAIN_MIN}m — add ~{rec} runner(s)")
                _STATE["last_scale_up_at"] = now
                _STATE["signals_emitted"] += 1
            elif sustained and in_cooldown:
                remaining = int((COOLDOWN_MIN * 60 - (now - _STATE["last_scale_up_at"])) / 60)
                reason = f"scale-up suppressed (cooldown {remaining}m remaining)"
                _STATE["cooldowns_suppressed"] += 1
        else:
            _STATE["over_since"] = None

            # --- Scale DOWN with hysteresis ---
            if under:
                _STATE["under_since"] = _STATE["under_since"] or now
                sustained_low = (now - _STATE["under_since"]) >= SUSTAIN_MIN * 60
                if sustained_low:
                    reason = (f"fleet idle (demand {wdemand:.0f} << ceiling {ceiling}) "
                              f"sustained >{SUSTAIN_MIN}m — a runner could stand down")
            else:
                _STATE["under_since"] = None
                if not reason:
                    reason = "within capacity"

    db.insert("autoscale_signals", {"queue_depth": depth, "weighted_demand": wdemand,
              "fleet_ceiling": ceiling, "recommend_workers": rec,
              "reason": reason or "within capacity"})
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
