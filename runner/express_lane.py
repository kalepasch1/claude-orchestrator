#!/usr/bin/env python3
"""
express_lane.py - Priority-pinned queue lane management for urgent/express tasks.

Reserves a configurable percentage of fleet lanes for high-priority express work,
routing tasks marked as priority='express' to the express lane, with fallback to
standard lanes if express capacity is exhausted.

Configuration (via fleet_config):
  ORCH_EXPRESS_LANE_ENABLED       bool, default: true
  ORCH_EXPRESS_LANE_CAPACITY_PCT  int 0-100, default: 15 (percentage of lanes)
"""
import os
import sys
import threading
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Configuration ────────────────────────────────────────────────────────────

def _get_config(key, default):
    """Get express lane config from fleet_config via environment."""
    try:
        val = os.environ.get(f"ORCH_{key}", "").strip()
        if not val:
            return default
        if isinstance(default, bool):
            return val.lower() in ("true", "1", "yes", "on")
        if isinstance(default, int):
            return int(val)
        return val
    except (ValueError, TypeError):
        return default

def is_enabled():
    """Check if express lane feature is enabled."""
    return _get_config("EXPRESS_LANE_ENABLED", True)

def capacity_percentage():
    """Get express lane capacity as percentage of total lanes (0-100)."""
    pct = _get_config("EXPRESS_LANE_CAPACITY_PCT", 15)
    return max(0, min(100, pct))  # Clamp to [0, 100]

# ── State tracking ───────────────────────────────────────────────────────────

# RLock: stats() and assign paths legitimately re-enter helpers that lock
_lock = threading.RLock()
_active_lanes = {
    "express": {},      # runner_id -> {"task_id": "...", "claimed_at": <time>}
    "standard": {},     # runner_id -> {"task_id": "...", "claimed_at": <time>}
}
_lane_assignments = {}  # task_id -> {"lane": "express"|"standard", "assigned_at": <time>, "fallback": bool}

#: Explicit override from set_total_lanes(); None means "ask the runner".
_total_lanes_override = None

#: Last-resort default, used only when MAX_PARALLEL is unreadable. Matches
#: runner.py's own MAX_PARALLEL default so the two cannot disagree silently.
_DEFAULT_TOTAL_LANES = 12


def total_lanes():
    """The machine's real lane count.

    Previously a module constant of 40 that `set_total_lanes()` was supposed to
    update — and nothing ever called it. The live limit is `MAX_PARALLEL`
    (runner.py:192, default 12, tuned per machine in runner/.env and pushable via
    fleet_config), so the capacity split was computed against a lane count that
    did not exist: on a 12-lane box, `ORCH_EXPRESS_LANE_CAPACITY_PCT=15` reserved
    `max(1, int(40 * 0.15))` = **6 lanes, i.e. 50% of the machine**, not 15%.

    Read live rather than cached, for the same reason runner.py checks eff_limit
    every dispatch loop: a boot-time snapshot silently pins the machine to
    whatever the value happened to be at boot.
    """
    if _total_lanes_override is not None:
        return _total_lanes_override
    try:
        return max(1, int(os.environ.get("MAX_PARALLEL", "") or _DEFAULT_TOTAL_LANES))
    except (TypeError, ValueError):  # fail-soft: a malformed env must not break claims
        return _DEFAULT_TOTAL_LANES


def set_total_lanes(count):
    """Pin the total lane count explicitly, overriding the MAX_PARALLEL read."""
    global _total_lanes_override
    try:
        _total_lanes_override = max(1, int(count))
    except (TypeError, ValueError):
        _total_lanes_override = None


def express_lane_capacity():
    """Compute the number of express lanes based on configuration."""
    if not is_enabled():
        return 0
    pct = capacity_percentage()
    if pct <= 0:
        return 0
    # Never hand the whole machine to express work: a reservation that leaves no
    # standard lane is a deadlock, not a priority.
    total = total_lanes()
    return max(1, min(total - 1, int(total * pct / 100))) if total > 1 else 1


def standard_lane_capacity():
    """Compute the number of standard lanes."""
    return total_lanes() - express_lane_capacity()


def _entries_of(value):
    """Normalize a lane-map value to a list of claim entries.

    Values are lists in normal operation, but a bare dict is accepted for
    backward compatibility (tests and older callers inject single entries).
    """
    if isinstance(value, list):
        return value
    return [value]


def _prune_stale_lanes():
    """Remove lane claims with stale task claims (>30 min old)."""
    cutoff = time.time() - 1800  # 30 minutes
    for lane_type in ("express", "standard"):
        for rid in list(_active_lanes[lane_type].keys()):
            fresh = [e for e in _entries_of(_active_lanes[lane_type][rid])
                     if e.get("claimed_at", 0) >= cutoff]
            if fresh:
                _active_lanes[lane_type][rid] = fresh
            else:
                del _active_lanes[lane_type][rid]


def _lane_count(lane_type):
    """Count active claims in a lane (a runner may hold several claims when
    runner ids collide, e.g. recycled thread idents)."""
    return sum(len(_entries_of(v)) for v in _active_lanes[lane_type].values())


def active_express_lanes():
    """Return count of currently active express lanes."""
    with _lock:
        _prune_stale_lanes()
        return _lane_count("express")


def active_standard_lanes():
    """Return count of currently active standard lanes."""
    with _lock:
        _prune_stale_lanes()
        return _lane_count("standard")


def express_lane_utilization():
    """Return (used, capacity, percent) for express lanes."""
    capacity = express_lane_capacity()
    if capacity <= 0:
        return 0, 0, 0.0
    used = active_express_lanes()
    percent = (used / capacity * 100) if capacity > 0 else 0.0
    return used, capacity, min(100.0, percent)


#: A task whose numeric priority is at or below this claims as express. `tasks.priority` is
#: an ASCENDING rank (db.claim_task sorts on it and defaults a missing value to 1000), so
#: "lower is more urgent" and a threshold well under the default is the express band.
EXPRESS_PRIORITY_AT_OR_BELOW = 100


def is_express_task(task):
    """Is this task express, per the REAL tasks schema? Returns (bool, reason).

    The original predicate was `str(task.get("priority")).lower() != "express"`, which cannot
    ever be true: `tasks.priority` is an INTEGER column. So every task answered
    "not_express_priority", should_use_express_lane() always returned False, and the whole
    module was inert — which is also why nothing outside its own tests ever imported it.

    The two express signals the schema actually provides:
      * pinned=true with a non-zero pin_rank — the operator's explicit "this goes first"
        marker, already honoured by claim ordering.
      * priority <= EXPRESS_PRIORITY_AT_OR_BELOW — an explicitly urgent numeric rank.
    """
    if not isinstance(task, dict):
        return False, "not_a_task"

    if task.get("pinned"):
        rank = task.get("pin_rank")
        if rank not in (None, 0):
            return True, "pinned"

    raw = task.get("priority")
    if raw is None or isinstance(raw, bool):
        return False, "no_priority"
    try:
        priority = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return False, "priority_not_numeric"
    if priority <= EXPRESS_PRIORITY_AT_OR_BELOW:
        return True, "express_priority"
    return False, "not_express_priority"


def should_use_express_lane(task):
    """Decide if a task should be routed to the express lane.

    Returns: (use_express, reason)
    """
    if not is_enabled():
        return False, "express_lane_disabled"

    express, reason = is_express_task(task)
    if not express:
        return False, reason

    # Check express lane capacity
    used, capacity, _ = express_lane_utilization()
    if used >= capacity:
        return False, "express_lane_full"

    return True, reason


def assign_task_lane(task_id, runner_id, use_express=False):
    """Record a task assignment to express or standard lane.

    Returns: {"lane": "express"|"standard", "fallback": bool}
    """
    with _lock:
        lane_type = "express" if use_express else "standard"
        # Append rather than overwrite: colliding runner ids (e.g. recycled
        # thread idents) must not silently drop an active claim.
        existing = _active_lanes[lane_type].get(runner_id)
        claims = _entries_of(existing) if existing is not None else []
        claims.append({
            "task_id": task_id,
            "claimed_at": time.time(),
        })
        _active_lanes[lane_type][runner_id] = claims
        assignment = {
            "lane": lane_type,
            "fallback": not use_express and use_express is not None,
            "assigned_at": datetime.now(timezone.utc).isoformat(),
        }
        _lane_assignments[task_id] = assignment
        return assignment


def get_task_lane_assignment(task_id):
    """Get the lane assignment for a task."""
    with _lock:
        return _lane_assignments.get(task_id)


def release_lane(runner_id):
    """Release a lane when a task completes.

    Multiple claims under one runner id are released oldest-first. An unknown id is an
    idempotent no-op: reclaiming an unrelated global claim would let a duplicate completion
    free another task's live capacity.
    """
    with _lock:
        for lane_type in ("express", "standard"):
            if runner_id in _active_lanes[lane_type]:
                claims = _entries_of(_active_lanes[lane_type][runner_id])
                claims.pop(0)
                if claims:
                    _active_lanes[lane_type][runner_id] = claims
                else:
                    del _active_lanes[lane_type][runner_id]


def stats():
    """Return comprehensive express lane statistics.

    The lock is intentionally reentrant because express_lane_utilization() traverses
    active_express_lanes(), which protects the same state. _lane_count() counts claims rather
    than runner-id keys, preserving the pinned-lane accounting fix when one runner id owns
    multiple concurrent claims.
    """
    with _lock:
        _prune_stale_lanes()
        express_used, express_cap, express_pct = express_lane_utilization()
        standard_used = _lane_count("standard")
        standard_cap = standard_lane_capacity()

        return {
            "enabled": is_enabled(),
            "capacity_percentage": capacity_percentage(),
            "total_lanes": total_lanes(),
            "express": {
                "capacity": express_cap,
                "active": express_used,
                "utilization_percent": express_pct,
            },
            "standard": {
                "capacity": standard_cap,
                "active": standard_used,
                "utilization_percent": (standard_used / standard_cap * 100) if standard_cap > 0 else 0.0,
            },
        }


def invalidate():
    """Clear all tracked lane state (for testing)."""
    global _active_lanes, _lane_assignments, _total_lanes_override
    with _lock:
        _active_lanes = {"express": {}, "standard": {}}
        _lane_assignments = {}
        _total_lanes_override = None
