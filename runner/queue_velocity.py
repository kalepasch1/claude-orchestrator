#!/usr/bin/env python3
"""
queue_velocity.py — PID-style queue velocity controller.

Tracks queue depth every 15 minutes. When the queue is growing (velocity positive for 2+
windows), proportionally throttle generators. When acceleration is positive (getting worse),
aggressively compact. When cumulative surplus (integral) is large, shelve lowest-EV work.

This replaces the blunt QUEUE_GEN_CEILING threshold with a smooth, adaptive controller
that keeps the queue draining without stalling improvement/recovery work.

Runs as a scheduled periodic job (every 15 minutes).
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
STATE_FILE = os.path.join(HOME, "queue_velocity_state.json")
WINDOW_S = 900  # 15 minutes
MAX_HISTORY = 20  # keep 5 hours of history

# Generator jobs that can be paused (never pause improve/remediate/recovery)
PAUSABLE_GENERATORS = {
    "bizradar", "demand_mining.py", "capability_radar.py", "scout", "spec",
    "promote", "roadmap", "newapp", "committees"
}
# Flag file: when present, _fire_periodic skips these generators
GENERATOR_PAUSE_FILE = os.path.join(HOME, "generator_pause.json")

# Thresholds
VELOCITY_PAUSE_THRESHOLD = 2       # positive velocity for N windows -> pause generators
ACCELERATION_COMPACT_THRESHOLD = 0  # if acceleration > 0 (getting worse), compact
INTEGRAL_SHELVE_THRESHOLD = 5000    # cumulative surplus tasks -> shelve lowest 20%
SHELVE_PCT = 0.20                   # fraction of queue to shelve when integral is too high


def _load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {"history": [], "integral": 0, "paused_at": None}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _queue_depth():
    # Exact header count is O(1), avoids PostgREST's 1,000-row body cap, and raises
    # on transport failure. An outage must never masquerade as a drained queue.
    return db.count("tasks", {"state": "eq.QUEUED"})


def _pause_generators(reason):
    """Write a pause file that _fire_periodic checks before launching generators."""
    with open(GENERATOR_PAUSE_FILE, "w") as f:
        json.dump({"paused": True, "reason": reason, "jobs": list(PAUSABLE_GENERATORS),
                    "at": time.time()}, f)
    print(f"[queue-velocity] PAUSED generators: {reason}")


def _unpause_generators():
    """Remove the pause file so generators can run again."""
    try:
        os.remove(GENERATOR_PAUSE_FILE)
        print("[queue-velocity] UNPAUSED generators (queue draining)")
    except FileNotFoundError:
        pass


def _shelve_lowest_ev(count):
    """Move the lowest-EV queued tasks to SHELVED state so the queue can drain."""
    try:
        # Get tasks ordered by confidence (lowest first = lowest EV)
        tasks = db.select("tasks", {"select": "id,slug,confidence",
                                     "state": "eq.QUEUED",
                                     "order": "confidence.asc.nullsfirst",
                                     "limit": str(count)}) or []
        shelved = 0
        for t in tasks:
            try:
                db.update("tasks", {"id": t["id"]},
                          {"state": "SHELVED",
                           "note": f"shelved by queue-velocity PID (low EV, integral too high)"})
                shelved += 1
            except Exception:
                pass
        if shelved:
            print(f"[queue-velocity] shelved {shelved} lowest-EV tasks to drain backlog")
        return shelved
    except Exception as e:
        print(f"[queue-velocity] shelve error: {e}")
        return 0


def run():
    state = _load_state()
    history = state.get("history", [])
    integral = state.get("integral", 0)

    # Sample current queue depth
    try:
        depth = _queue_depth()
    except Exception as e:
        print(f"[queue-velocity] measurement failed; preserving controller state: {e}")
        return {"ok": False, "error": str(e), "measurement_valid": False}
    now = time.time()
    history.append({"t": now, "depth": depth})
    history = history[-MAX_HISTORY:]  # trim

    # Compute velocity (dQ/dt) — change per window
    velocity = 0
    if len(history) >= 2:
        velocity = history[-1]["depth"] - history[-2]["depth"]

    # Compute acceleration (d²Q/dt²) — change in velocity
    acceleration = 0
    if len(history) >= 3:
        prev_velocity = history[-2]["depth"] - history[-3]["depth"]
        acceleration = velocity - prev_velocity

    # Update integral (cumulative surplus)
    if velocity > 0:
        integral += velocity
    else:
        integral = max(0, integral + velocity)  # drain integral when queue shrinks

    # Count consecutive positive-velocity windows
    consecutive_positive = 0
    for i in range(len(history) - 1, 0, -1):
        if history[i]["depth"] > history[i-1]["depth"]:
            consecutive_positive += 1
        else:
            break

    # --- PID ACTIONS ---

    # P (proportional): pause generators when velocity positive for 2+ windows
    if consecutive_positive >= VELOCITY_PAUSE_THRESHOLD:
        _pause_generators(f"velocity positive for {consecutive_positive} windows "
                         f"(depth={depth}, velocity={velocity:+d})")
    elif velocity <= 0:
        _unpause_generators()

    # D (derivative): aggressive compact when acceleration positive
    if acceleration > 0 and consecutive_positive >= 2 and depth > 200:
        # Queue is growing AND getting worse — compact aggressively
        compact_count = min(50, int(depth * 0.05))
        _shelve_lowest_ev(compact_count)
        print(f"[queue-velocity] D-action: compacted {compact_count} (acceleration={acceleration:+d})")

    # I (integral): shelve lowest-EV when cumulative surplus is too high
    if integral > INTEGRAL_SHELVE_THRESHOLD and depth > 500:
        shelve_count = int(depth * SHELVE_PCT)
        _shelve_lowest_ev(shelve_count)
        integral = max(0, integral - shelve_count)  # reduce integral after shelving
        print(f"[queue-velocity] I-action: shelved {shelve_count} (integral={integral})")

    # Log state
    print(f"[queue-velocity] depth={depth} velocity={velocity:+d} accel={acceleration:+d} "
          f"integral={integral} consecutive_positive={consecutive_positive}")

    state = {"history": history, "integral": integral, "paused_at": state.get("paused_at")}
    _save_state(state)
    return {"depth": depth, "velocity": velocity, "acceleration": acceleration,
            "integral": integral, "consecutive_positive": consecutive_positive}


def is_generator_paused(job_name):
    """Called by _fire_periodic to check if a generator should be skipped."""
    try:
        data = json.load(open(GENERATOR_PAUSE_FILE))
        if data.get("paused") and job_name in (data.get("jobs") or []):
            # Auto-expire after 2 hours (safety valve)
            if time.time() - data.get("at", 0) > 7200:
                _unpause_generators()
                return False
            return True
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return False


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
