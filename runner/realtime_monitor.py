#!/usr/bin/env python3
"""
realtime_monitor.py – Real-time task monitoring and approval dashboard data provider.

Aggregates live orchestrator state into dashboard-ready snapshots: queue depths,
throughput rates, pending approvals, and per-project health. Powers the ops
approval dashboard with sub-minute data.

Conventions: module-level singleton, fail-soft, ORCH_ env vars, thread-safe.
"""
import os, sys, json, datetime, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SNAPSHOT_TTL = int(os.environ.get("ORCH_MONITOR_TTL_SEC", "30"))
APPROVAL_STATES = ("PENDING_REVIEW", "NEEDS_APPROVAL")

_lock = threading.Lock()
_STATE = {
    "last_snapshot": None,
    "snapshot_at": None,
    "snapshot_count": 0,
}


def _queue_depths():
    """Current task counts by state."""
    try:
        import db
        rows = db.sql(
            "SELECT state, count(*)::int AS cnt FROM tasks GROUP BY state"
        ) or []
        return {r["state"]: r["cnt"] for r in rows}
    except Exception:
        return {}


def _throughput(window_hours=1):
    """Tasks completed in the last N hours."""
    try:
        import db
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=window_hours)).isoformat() + "Z"
        rows = db.select("tasks", {
            "select": "id",
            "state": "eq.DONE",
            "updated_at": f"gte.{cutoff}",
        }) or []
        return len(rows)
    except Exception:
        return 0


def _pending_approvals():
    """Tasks waiting for human approval."""
    try:
        import db
        rows = db.select("tasks", {
            "select": "slug,kind,project_id,note,updated_at",
            "or": ",".join(f"(state.eq.{s})" for s in APPROVAL_STATES),
            "order": "updated_at.asc",
            "limit": "50",
        }) or []
        return [
            {
                "slug": r.get("slug"),
                "kind": r.get("kind"),
                "project_id": r.get("project_id"),
                "waiting_since": r.get("updated_at"),
                "note_preview": (r.get("note") or "")[:100],
            }
            for r in rows
        ]
    except Exception:
        return []


def _project_summary():
    """Per-project task state breakdown."""
    try:
        import db
        rows = db.sql(
            "SELECT p.name, t.state, count(*)::int AS cnt "
            "FROM tasks t JOIN projects p ON t.project_id = p.id "
            "GROUP BY p.name, t.state ORDER BY p.name"
        ) or []
        summary = {}
        for r in rows:
            name = r.get("name", "unknown")
            summary.setdefault(name, {})[r.get("state", "?")] = r.get("cnt", 0)
        return summary
    except Exception:
        return {}


def snapshot():
    """
    Capture a point-in-time dashboard snapshot.

    Returns dict with queue_depths, throughput_1h, pending_approvals,
    project_summary, and timestamp.
    """
    now = datetime.datetime.utcnow().isoformat() + "Z"

    # Check TTL cache
    with _lock:
        if (_STATE["snapshot_at"] and _STATE["last_snapshot"]
                and (datetime.datetime.utcnow() -
                     datetime.datetime.fromisoformat(
                         _STATE["snapshot_at"].rstrip("Z")
                     )).total_seconds() < SNAPSHOT_TTL):
            return _STATE["last_snapshot"]

    depths = _queue_depths()
    result = {
        "queue_depths": depths,
        "total_tasks": sum(depths.values()),
        "throughput_1h": _throughput(1),
        "throughput_24h": _throughput(24),
        "pending_approvals": _pending_approvals(),
        "pending_count": 0,
        "project_summary": _project_summary(),
        "snapshot_at": now,
    }
    result["pending_count"] = len(result["pending_approvals"])

    with _lock:
        _STATE["last_snapshot"] = result
        _STATE["snapshot_at"] = now
        _STATE["snapshot_count"] += 1

    return result


def approval_queue():
    """Return just the pending approvals for the dashboard widget."""
    return _pending_approvals()


def stats():
    """Return cached monitor state."""
    with _lock:
        return {
            "snapshot_at": _STATE["snapshot_at"],
            "snapshot_count": _STATE["snapshot_count"],
        }


def run():
    """Entry point for orchestrator periodic jobs."""
    snap = snapshot()
    try:
        import db
        depths_str = ", ".join(f"{k}={v}" for k, v in snap["queue_depths"].items())
        db.insert("inbox", {
            "kind": "monitor_snapshot",
            "title": f"Monitor: {snap['total_tasks']} tasks, "
                     f"{snap['throughput_1h']} done/1h, "
                     f"{snap['pending_count']} awaiting approval",
            "body": f"Queue: {depths_str}\n"
                    f"Throughput 24h: {snap['throughput_24h']}\n"
                    f"Pending approvals: {snap['pending_count']}",
            "created_at": snap["snapshot_at"],
        })
    except Exception:
        pass
    return snap


if __name__ == "__main__":
    print(json.dumps(snapshot(), indent=2, default=str))
