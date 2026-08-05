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

_lock = threading.Lock()
_active_lanes = {
    "express": {},      # runner_id -> {"task_id": "...", "claimed_at": <time>}
    "standard": {},     # runner_id -> {"task_id": "...", "claimed_at": <time>}
}
_lane_assignments = {}  # task_id -> {"lane": "express"|"standard", "assigned_at": <time>, "fallback": bool}
_total_lanes = 40       # Default; updated by capacity function


def set_total_lanes(count):
    """Set the total number of available lanes (used for capacity calculation)."""
    global _total_lanes
    _total_lanes = max(1, count)


def express_lane_capacity():
    """Compute the number of express lanes based on configuration."""
    if not is_enabled():
        return 0
    pct = capacity_percentage()
    return max(1, int(_total_lanes * pct / 100)) if pct > 0 else 0


def standard_lane_capacity():
    """Compute the number of standard lanes."""
    return _total_lanes - express_lane_capacity()


def _prune_stale_lanes():
    """Remove lanes with stale task claims (>30 min old)."""
    cutoff = time.time() - 1800  # 30 minutes
    for lane_type in ("express", "standard"):
        stale = [rid for rid, data in _active_lanes[lane_type].items()
                if data.get("claimed_at", 0) < cutoff]
        for rid in stale:
            del _active_lanes[lane_type][rid]


def active_express_lanes():
    """Return count of currently active express lanes."""
    with _lock:
        _prune_stale_lanes()
        return len(_active_lanes["express"])


def active_standard_lanes():
    """Return count of currently active standard lanes."""
    with _lock:
        _prune_stale_lanes()
        return len(_active_lanes["standard"])


def express_lane_utilization():
    """Return (used, capacity, percent) for express lanes."""
    capacity = express_lane_capacity()
    if capacity <= 0:
        return 0, 0, 0.0
    used = active_express_lanes()
    percent = (used / capacity * 100) if capacity > 0 else 0.0
    return used, capacity, min(100.0, percent)


def should_use_express_lane(task):
    """Decide if a task should be routed to the express lane.

    Returns: (use_express, reason)
    """
    if not is_enabled():
        return False, "express_lane_disabled"

    # Check task priority
    priority = str(task.get("priority", "")).lower()
    if priority != "express":
        return False, "not_express_priority"

    # Check express lane capacity
    used, capacity, _ = express_lane_utilization()
    if used >= capacity:
        return False, "express_lane_full"

    return True, "express_priority"


def assign_task_lane(task_id, runner_id, use_express=False):
    """Record a task assignment to express or standard lane.

    Returns: {"lane": "express"|"standard", "fallback": bool}
    """
    with _lock:
        lane_type = "express" if use_express else "standard"
        _active_lanes[lane_type][runner_id] = {
            "task_id": task_id,
            "claimed_at": time.time(),
        }
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
    """Release a lane when a task completes."""
    with _lock:
        for lane_type in ("express", "standard"):
            if runner_id in _active_lanes[lane_type]:
                del _active_lanes[lane_type][runner_id]


def stats():
    """Return comprehensive express lane statistics."""
    with _lock:
        _prune_stale_lanes()
        express_used, express_cap, express_pct = express_lane_utilization()
        standard_used = len(_active_lanes["standard"])
        standard_cap = standard_lane_capacity()

        return {
            "enabled": is_enabled(),
            "capacity_percentage": capacity_percentage(),
            "total_lanes": _total_lanes,
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
    global _active_lanes, _lane_assignments
    with _lock:
        _active_lanes = {"express": {}, "standard": {}}
        _lane_assignments = {}
