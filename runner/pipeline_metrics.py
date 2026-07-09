#!/usr/bin/env python3
"""
pipeline_metrics.py - test pipeline observability. Records per-run metrics (duration,
pass/fail, gate decision) keyed by task type, and exposes health queries.

Fail-soft throughout: metric loss is always preferable to wedging the merge train.
"""
import datetime, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

TABLE = "pipeline_metrics"


def record(slug, task_type, ok, duration_ms, gate_decision, gate_reason=""):
    """Persist one test-run metric row. Silently swallows all errors."""
    row = {
        "slug": slug or "",
        "task_type": task_type or "unknown",
        "passed": bool(ok),
        "duration_ms": int(duration_ms or 0),
        "gate_decision": gate_decision or "",
        "gate_reason": (gate_reason or "")[:500],
        "recorded_at": datetime.datetime.utcnow().isoformat(),
    }
    try:
        db.insert(TABLE, row)
    except Exception:
        pass


def get_health(lookback_minutes=60, task_type=None):
    """Aggregate pass rates and durations by task type for the given lookback window.

    Returns {"lookback_minutes": int, "by_task_type": {type: {total, passed, failed,
    pass_rate, avg_duration_ms, gate_decisions}}}. Fail-soft: returns empty on DB error.
    """
    cutoff = (
        datetime.datetime.utcnow() - datetime.timedelta(minutes=lookback_minutes)
    ).isoformat()
    params = {
        "select": "*",
        "recorded_at": f"gte.{cutoff}",
        "order": "recorded_at.desc",
        "limit": "5000",
    }
    if task_type:
        params["task_type"] = f"eq.{task_type}"
    try:
        rows = db.select(TABLE, params) or []
    except Exception:
        rows = []

    by_type = {}
    for r in rows:
        tt = r.get("task_type") or "unknown"
        if tt not in by_type:
            by_type[tt] = {"total": 0, "passed": 0, "total_ms": 0, "gate_decisions": {}}
        g = by_type[tt]
        g["total"] += 1
        if r.get("passed"):
            g["passed"] += 1
        g["total_ms"] += int(r.get("duration_ms") or 0)
        gd = r.get("gate_decision") or "unknown"
        g["gate_decisions"][gd] = g["gate_decisions"].get(gd, 0) + 1

    result = {}
    for tt, g in by_type.items():
        n = g["total"]
        result[tt] = {
            "total": n,
            "passed": g["passed"],
            "failed": n - g["passed"],
            "pass_rate": round(g["passed"] / n, 3) if n else 0.0,
            "avg_duration_ms": round(g["total_ms"] / n) if n else 0,
            "gate_decisions": g["gate_decisions"],
        }
    return {"lookback_minutes": lookback_minutes, "by_task_type": result}


if __name__ == "__main__":
    import json
    print(json.dumps(get_health(), indent=2))
