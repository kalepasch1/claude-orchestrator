#!/usr/bin/env python3
"""
fleet_health_score.py — composite fleet health metric for autoscale decisions.

Combines queue velocity, failure rate, worker utilization, and staleness
into a single 0-100 health score. Low scores trigger investigation;
very low scores feed into autoscale_signal as a scale-up amplifier.

Env vars:
    ORCH_FLEET_HEALTH_ENABLED     "true" to enable (default "true")
    ORCH_HEALTH_FAILURE_WEIGHT    weight for failure rate (default 0.3)
    ORCH_HEALTH_VELOCITY_WEIGHT   weight for queue velocity (default 0.3)
    ORCH_HEALTH_UTIL_WEIGHT       weight for utilization (default 0.2)
    ORCH_HEALTH_STALE_WEIGHT      weight for staleness (default 0.2)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENABLED = os.environ.get("ORCH_FLEET_HEALTH_ENABLED", "true").lower() in ("1", "true", "yes")
W_FAIL = float(os.environ.get("ORCH_HEALTH_FAILURE_WEIGHT", "0.3"))
W_VEL = float(os.environ.get("ORCH_HEALTH_VELOCITY_WEIGHT", "0.3"))
W_UTIL = float(os.environ.get("ORCH_HEALTH_UTIL_WEIGHT", "0.2"))
W_STALE = float(os.environ.get("ORCH_HEALTH_STALE_WEIGHT", "0.2"))


def _failure_score():
    """Score based on recent failure rate. 100 = no failures, 0 = all failing."""
    try:
        import db
        recent = db.select("tasks", {
            "select": "state",
            "updated_at": f"gte.{time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(time.time() - 3600))}",
        }) or []
    except Exception:
        return 50.0  # can't measure → neutral
    if not recent:
        return 100.0
    fail_states = {"QUARANTINED", "BLOCKED", "FAILED", "ERROR"}
    failures = sum(1 for r in recent if r.get("state") in fail_states)
    rate = failures / len(recent)
    return max(0.0, 100.0 * (1.0 - rate))


def _velocity_score():
    """Score based on DONE tasks per hour. 100 = healthy throughput."""
    try:
        import db
        done = db.select("tasks", {
            "select": "id",
            "state": "eq.DONE",
            "updated_at": f"gte.{time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(time.time() - 3600))}",
        }) or []
        queued = db.select("tasks", {"select": "id", "state": "eq.QUEUED"}) or []
    except Exception:
        return 50.0
    done_count = len(done)
    queued_count = len(queued)
    if queued_count == 0:
        return 100.0  # nothing waiting
    # Ratio of throughput to demand
    ratio = done_count / max(1, queued_count)
    return min(100.0, ratio * 100.0)


def _utilization_score():
    """Score based on worker utilization. 100 = balanced, low = over/under."""
    try:
        import db
        running = len(db.select("tasks", {"select": "id", "state": "eq.RUNNING"}) or [])
        try:
            import fleet
            cap = fleet.capacity()
            ceiling = cap.get("ceiling", 0) or 0
        except Exception:
            ceiling = 0
    except Exception:
        return 50.0
    if ceiling == 0:
        return 50.0
    util = running / ceiling
    # Optimal is 0.5-0.8 utilization
    if 0.5 <= util <= 0.8:
        return 100.0
    elif util < 0.5:
        return max(0.0, util / 0.5 * 100.0)
    else:  # > 0.8, overloaded
        return max(0.0, 100.0 - (util - 0.8) / 0.2 * 100.0)


def _staleness_score():
    """Score based on queue staleness. 100 = fresh, 0 = stale queue."""
    try:
        import db
        stale = db.select("tasks", {
            "select": "id",
            "state": "eq.QUEUED",
            "updated_at": f"lt.{time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(time.time() - 86400))}",
        }) or []
        total = db.select("tasks", {"select": "id", "state": "eq.QUEUED"}) or []
    except Exception:
        return 50.0
    if not total:
        return 100.0
    stale_ratio = len(stale) / len(total)
    return max(0.0, 100.0 * (1.0 - stale_ratio))


def compute_health():
    """Compute composite fleet health score (0-100)."""
    if not ENABLED:
        return {"score": -1, "reason": "disabled"}
    f = _failure_score()
    v = _velocity_score()
    u = _utilization_score()
    s = _staleness_score()
    score = round(W_FAIL * f + W_VEL * v + W_UTIL * u + W_STALE * s, 1)
    status = "healthy" if score >= 70 else "degraded" if score >= 40 else "critical"
    return {
        "score": score, "status": status,
        "components": {"failure": round(f, 1), "velocity": round(v, 1),
                       "utilization": round(u, 1), "staleness": round(s, 1)},
    }


def run():
    result = compute_health()
    print(f"fleet_health: {result.get('score', -1)} ({result.get('status', 'unknown')})")
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
