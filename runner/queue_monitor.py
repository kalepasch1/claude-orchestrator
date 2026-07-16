"""
queue_monitor.py — real-time queue monitoring with alerting for critical conditions.

Tracks queue state snapshots, detects anomalies (prolonged wait times, test failures,
stale tasks), and logs structured alerts. Designed to run as a periodic job in the
orchestrator runner.
"""
import os, sys, time, json, logging, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

log = logging.getLogger(__name__)

# Alert thresholds (configurable via env)
MAX_WAIT_HOURS = float(os.environ.get("ORCH_MONITOR_MAX_WAIT_H", "4"))
MAX_RUNNING_HOURS = float(os.environ.get("ORCH_MONITOR_MAX_RUNNING_H", "2"))
STALE_BLOCKED_HOURS = float(os.environ.get("ORCH_MONITOR_STALE_BLOCKED_H", "24"))
MIN_MERGE_RATE = float(os.environ.get("ORCH_MONITOR_MIN_MERGE_RATE", "0.1"))


def snapshot_queue_states():
    """Take a snapshot of current queue states.

    Returns dict of state -> count.
    """
    states = {}
    for state in ("QUEUED", "RUNNING", "DONE", "MERGED", "BLOCKED", "TESTFAIL",
                  "BUILDFAIL", "SHELVED", "DECOMPOSED", "QUARANTINED"):
        try:
            states[state] = db.count("tasks", {"state": f"eq.{state}"}) or 0
        except Exception:
            states[state] = 0
    return states


def detect_alerts(states=None):
    """Detect critical conditions in the queue.

    Returns list of alert dicts: {severity, category, message, details}.
    """
    if states is None:
        states = snapshot_queue_states()

    alerts = []
    now = datetime.datetime.utcnow()
    cutoff_fmt = lambda h: (now - datetime.timedelta(hours=h)).isoformat()

    # 1. Check for tasks waiting too long in QUEUED
    try:
        old_queued = db.select("tasks", {
            "select": "id,slug,project_id,created_at",
            "state": "eq.QUEUED",
            "created_at": f"lt.{cutoff_fmt(MAX_WAIT_HOURS)}",
            "order": "created_at.asc",
            "limit": "10",
        }) or []
        if old_queued:
            alerts.append({
                "severity": "warning",
                "category": "long_wait",
                "message": f"{len(old_queued)} tasks queued > {MAX_WAIT_HOURS}h",
                "details": [t.get("slug") for t in old_queued[:5]],
            })
    except Exception as e:
        log.debug("queue_monitor: long_wait check failed: %s", e)

    # 2. Check for tasks stuck RUNNING too long
    try:
        stuck_running = db.select("tasks", {
            "select": "id,slug,account,updated_at",
            "state": "eq.RUNNING",
            "updated_at": f"lt.{cutoff_fmt(MAX_RUNNING_HOURS)}",
            "limit": "10",
        }) or []
        if stuck_running:
            alerts.append({
                "severity": "critical",
                "category": "stuck_running",
                "message": f"{len(stuck_running)} tasks stuck RUNNING > {MAX_RUNNING_HOURS}h",
                "details": [{"slug": t.get("slug"), "account": t.get("account")} for t in stuck_running[:5]],
            })
    except Exception as e:
        log.debug("queue_monitor: stuck_running check failed: %s", e)

    # 3. Check for stale blocked tasks
    try:
        stale_blocked = db.count("tasks", {
            "state": "in.(BLOCKED,TESTFAIL,BUILDFAIL)",
            "updated_at": f"lt.{cutoff_fmt(STALE_BLOCKED_HOURS)}",
        }) or 0
        if stale_blocked > 5:
            alerts.append({
                "severity": "warning",
                "category": "stale_blocked",
                "message": f"{stale_blocked} tasks blocked/failing > {STALE_BLOCKED_HOURS}h",
                "details": {"count": stale_blocked},
            })
    except Exception as e:
        log.debug("queue_monitor: stale_blocked check failed: %s", e)

    # 4. Check merge rate
    total_done = states.get("DONE", 0)
    total_merged = states.get("MERGED", 0)
    if total_done + total_merged > 10:
        merge_rate = total_merged / max(1, total_done + total_merged)
        if merge_rate < MIN_MERGE_RATE:
            alerts.append({
                "severity": "warning",
                "category": "low_merge_rate",
                "message": f"Merge rate {merge_rate:.1%} below threshold {MIN_MERGE_RATE:.1%}",
                "details": {"done": total_done, "merged": total_merged, "rate": round(merge_rate, 3)},
            })

    # 5. Check if queue is completely stalled (nothing running)
    if states.get("QUEUED", 0) > 10 and states.get("RUNNING", 0) == 0:
        alerts.append({
            "severity": "critical",
            "category": "queue_stalled",
            "message": f"Queue stalled: {states['QUEUED']} queued, 0 running",
            "details": states,
        })

    return alerts


def log_snapshot(states=None, alerts=None):
    """Log a queue health snapshot with any active alerts."""
    if states is None:
        states = snapshot_queue_states()
    if alerts is None:
        alerts = detect_alerts(states)

    snapshot = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "states": states,
        "alert_count": len(alerts),
        "alerts": alerts,
    }

    if alerts:
        critical = [a for a in alerts if a["severity"] == "critical"]
        if critical:
            log.error("queue_monitor: %d critical alerts: %s",
                      len(critical), "; ".join(a["message"] for a in critical))
        else:
            log.warning("queue_monitor: %d alerts: %s",
                        len(alerts), "; ".join(a["message"] for a in alerts))
    else:
        log.info("queue_monitor: healthy — %s", json.dumps(states))

    return snapshot


def run():
    """Periodic job entry point."""
    states = snapshot_queue_states()
    alerts = detect_alerts(states)
    snapshot = log_snapshot(states, alerts)
    return snapshot


if __name__ == "__main__":
    snapshot = run()
    print(json.dumps(snapshot, indent=2, default=str))
