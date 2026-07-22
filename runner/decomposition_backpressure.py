#!/usr/bin/env python3
"""
decomposition_backpressure.py — Watermark gate for task decomposition.

Prevents unbounded decomposition when the fleet can't keep up. Stops decomposing
new tasks if the backlog of decomposed-but-not-yet-running work exceeds a watermark
tied to observed runner capacity:

    watermark = (DECOMPOSED count - RUNNING count - MERGED count) > 10 × peak_runner_count

This keeps the decomposition pipeline from flooding the queue with work that no
runner will pick up for hours, which wastes planner tokens and makes queue health
metrics meaningless.

Called by auto_remediate.py and bankruptcy_decompose.py before spawning sub-tasks.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Multiplier: stop decomposing if backlog > N × peak runners
WATERMARK_MULTIPLIER = int(os.environ.get("ORCH_DECOMPOSE_WATERMARK_MULT", "10"))

# Minimum peak runner count (floor so we don't divide by zero on cold start)
MIN_PEAK_RUNNERS = int(os.environ.get("ORCH_MIN_PEAK_RUNNERS", "2"))


def _get_peak_runner_count():
    """Read the peak observed runner count from fleet_config. Fail-soft."""
    try:
        rows = db.select("fleet_config", {
            "select": "value",
            "key": "eq.peak_runner_count",
        }) or []
        if rows:
            return max(int(rows[0].get("value", MIN_PEAK_RUNNERS)), MIN_PEAK_RUNNERS)
    except Exception:
        pass
    return MIN_PEAK_RUNNERS


def _get_queue_state_counts(project_id=None):
    """Get counts of DECOMPOSED, RUNNING, and MERGED tasks. Fail-soft."""
    counts = {"DECOMPOSED": 0, "RUNNING": 0, "MERGED": 0}
    try:
        for state in counts:
            params = {"state": f"eq.{state}", "select": "id"}
            if project_id:
                params["project_id"] = f"eq.{project_id}"
            count = db.count("tasks", params)
            counts[state] = count or 0
    except Exception:
        pass
    return counts


def _update_peak_runners(current_running):
    """Track peak runner count in fleet_config. Fail-soft."""
    try:
        current_peak = _get_peak_runner_count()
        if current_running > current_peak:
            db.insert("fleet_config", {
                "key": "peak_runner_count",
                "value": str(current_running),
            }, on_conflict="key", merge_patch={"value": "EXCLUDED.value"})
    except Exception:
        pass


def can_decompose(project_id=None):
    """Check if decomposition is allowed given current queue pressure.

    Returns:
        (allowed: bool, reason: str)
    """
    counts = _get_queue_state_counts(project_id)
    peak_runners = _get_peak_runner_count()

    # Update peak runner tracking
    _update_peak_runners(counts["RUNNING"])

    backlog = counts["DECOMPOSED"] - counts["RUNNING"] - counts["MERGED"]
    watermark = WATERMARK_MULTIPLIER * peak_runners

    if backlog > watermark:
        return False, (
            f"decomposition paused: backlog {backlog} > watermark {watermark} "
            f"(DECOMPOSED={counts['DECOMPOSED']}, RUNNING={counts['RUNNING']}, "
            f"MERGED={counts['MERGED']}, peak_runners={peak_runners})"
        )

    return True, f"ok: backlog {backlog} <= watermark {watermark}"


def gate(task=None, project_id=None):
    """Convenience wrapper: returns True if decomposition is allowed.

    If task is provided, extracts project_id from it.
    """
    pid = project_id or (task or {}).get("project_id")
    allowed, reason = can_decompose(pid)
    if not allowed:
        try:
            # Log the backpressure event for observability
            db.insert("fleet_config", {
                "key": f"decompose_backpressure:{int(time.time())}",
                "value": reason[:500],
            }, on_conflict="key", merge_patch={"value": "EXCLUDED.value"})
        except Exception:
            pass
    return allowed
