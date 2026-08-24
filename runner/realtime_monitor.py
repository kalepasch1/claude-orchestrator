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
        # None, not {}. An empty queue and an unreachable control plane are opposite
        # facts; a monitor that renders them identically is worse than no monitor.
        return None


def _throughput(window_hours=1):
    """Tasks completed in the last N hours. None when the count is unavailable.

    Two bugs lived in one line here.

    COUNT BY FETCH. This selected rows and returned len(). PostgREST caps a response at
    1000 rows whatever the query asks for, so throughput SATURATED at 1000 — past that
    the dashboard showed the same number no matter how much the fleet actually did, and
    the 24h window hit the ceiling long before the 1h window did, making 24h look *worse*
    than 1h. db.count asks the server for the exact number and transfers no rows.

    OUTAGE RENDERED AS ZERO. The except returned 0, which on a MONITORING surface is the
    worst possible default: a control-plane outage and a fleet that completed nothing
    produce the identical reading, so the dashboard is calmest exactly when it should be
    loudest. None means UNKNOWN and callers must not render it as 0.
    """
    try:
        import db
        cutoff = (datetime.datetime.utcnow()
                  - datetime.timedelta(hours=window_hours)).isoformat() + "Z"
        got = db.count("tasks", {"state": "eq.DONE", "updated_at": f"gte.{cutoff}"})
        return int(got or 0)
    except Exception:
        return None


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
        return None  # UNKNOWN, not "nothing is waiting" — see _throughput.


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
        return None  # UNKNOWN, not "no projects" — see _throughput.


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
    approvals = _pending_approvals()
    result = {
        "queue_depths": depths if depths is not None else {},
        # `is not None`, not truthiness: an EMPTY depths dict means a genuinely empty
        # queue and must total 0, while None means we could not ask.
        "total_tasks": sum(depths.values()) if depths is not None else None,
        "throughput_1h": _throughput(1),
        "throughput_24h": _throughput(24),
        "pending_approvals": approvals if approvals is not None else [],
        "pending_count": len(approvals) if approvals is not None else None,
        "project_summary": _project_summary(),
        "snapshot_at": now,
    }
    # DEGRADED is the field a dashboard must read before it renders anything. Every
    # metric that could not be measured is named here, so an outage is visible as an
    # outage instead of as a very quiet fleet. A snapshot with a non-empty `degraded`
    # list must never be presented as a healthy reading.
    result["degraded"] = sorted(
        name for name in ("queue_depths", "throughput_1h", "throughput_24h",
                          "pending_count", "project_summary")
        if (depths is None and name == "queue_depths")
        or (result.get(name) is None and name != "queue_depths"))
    result["ok"] = not result["degraded"]

    with _lock:
        _STATE["last_snapshot"] = result
        _STATE["snapshot_at"] = now
        _STATE["snapshot_count"] += 1

    return result


def approval_queue():
    """Pending approvals for the dashboard widget. [] when unavailable.

    This one keeps the list contract because the widget iterates it directly; callers
    that need to distinguish "none waiting" from "could not ask" should read
    `snapshot()["degraded"]`.
    """
    got = _pending_approvals()
    return got if got is not None else []


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
        def _fmt(value):
            # "unknown" is spelled out. "None tasks" in an inbox title reads like a
            # formatting bug and gets ignored; "unknown" reads like an outage.
            return "unknown" if value is None else value

        depths_str = ", ".join(f"{k}={v}" for k, v in snap["queue_depths"].items())
        prefix = "Monitor" if snap.get("ok", True) else "Monitor DEGRADED"
        db.insert("inbox", {
            "kind": "monitor_snapshot",
            "title": f"{prefix}: {_fmt(snap['total_tasks'])} tasks, "
                     f"{_fmt(snap['throughput_1h'])} done/1h, "
                     f"{_fmt(snap['pending_count'])} awaiting approval",
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
