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


# ── alert delivery ────────────────────────────────────────────────────────────────────
# detect_alerts() has always found prolonged waits, stuck RUNNING tasks and a stalled
# queue — and then only written them to a log file nobody is watching. An alert that is
# only logged is not an alert. These deliver criticals through notify.py (Slack + email
# via scripts/notify.sh), with a per-condition cooldown so a condition that persists for
# hours pages once per window instead of once per run.
ALERTS_ENABLED = os.environ.get("ORCH_MONITOR_ALERTS_ENABLED", "true").lower() in (
    "1", "true", "yes", "on")
ALERT_COOLDOWN_MIN = float(os.environ.get("ORCH_MONITOR_ALERT_COOLDOWN_MIN", "60") or 60)
#: Only these severities are delivered. Warnings stay in the log by design — paging on
#: every warning is how an alert channel gets muted, which costs more than it saves.
ALERT_SEVERITIES = tuple(
    s.strip().lower()
    for s in os.environ.get("ORCH_MONITOR_ALERT_SEVERITIES", "critical").split(",")
    if s.strip()
)
_HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
ALERT_STATE_FILE = os.path.join(_HOME, "queue_monitor_alerts.json")


def alert_fingerprint(alert):
    """Stable identity of a CONDITION, not of one observation.

    Deliberately excludes `details` and the counts inside `message`: "3 tasks stuck" and
    "4 tasks stuck" are the same ongoing incident, and keying on the exact wording would
    defeat the cooldown every time one more task piles on.
    """
    if not isinstance(alert, dict):
        return ""
    return f"{alert.get('severity', '')}:{alert.get('category', '')}"


def _load_alert_state(path=None):
    try:
        with open(path or ALERT_STATE_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_alert_state(state, path=None):
    path = path or ALERT_STATE_FILE
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        return True
    except Exception as exc:
        log.debug("queue_monitor: could not persist alert state: %s", exc)
        return False


def alerts_to_deliver(alerts, state=None, now=None, cooldown_min=None):
    """Which alerts are due for delivery. Pure — no I/O, no clock, fully testable.

    Returns (to_send, next_state). An unknown/garbage severity is never delivered:
    guessing that an unrecognised level is critical would page on parser bugs.
    """
    state = dict(state or {})
    now = time.time() if now is None else now
    window = (ALERT_COOLDOWN_MIN if cooldown_min is None else cooldown_min) * 60.0
    to_send = []
    for alert in alerts or []:
        if not isinstance(alert, dict):
            continue
        if str(alert.get("severity", "")).lower() not in ALERT_SEVERITIES:
            continue
        key = alert_fingerprint(alert)
        # Absent or unreadable means NEVER SENT, not "sent at epoch 0" — a corrupt
        # bookkeeping entry must fail towards delivering the alert, never towards
        # silencing it.
        raw = state.get(key)
        try:
            last = None if raw in (None, "") else float(raw)
        except (TypeError, ValueError):
            last = None
        if last is not None and now - last < window:
            continue
        to_send.append(alert)
        state[key] = now
    return to_send, state


def format_alert(alert):
    """One-line, channel-agnostic rendering. Never raises on an odd alert shape."""
    if not isinstance(alert, dict):
        return "queue-monitor: malformed alert"
    severity = str(alert.get("severity", "alert")).upper()
    message = str(alert.get("message", "")).strip() or str(alert.get("category", "?"))
    return f"[queue-monitor {severity}] {message}"


def dispatch_alerts(alerts, state_path=None, sender=None):
    """Deliver due alerts through notify.py. Fail-soft — monitoring never wedges a run.

    Returns the list of messages actually sent.
    """
    if not ALERTS_ENABLED or not alerts:
        return []
    path = state_path or ALERT_STATE_FILE
    state = _load_alert_state(path)
    due, next_state = alerts_to_deliver(alerts, state)
    if not due:
        return []
    if sender is None:
        try:
            import notify
            sender = notify.send
        except Exception as exc:
            log.warning("queue_monitor: notify unavailable (%s); alerts logged only", exc)
            return []
    sent = []
    for alert in due:
        message = format_alert(alert)
        try:
            sender(message)
            sent.append(message)
        except Exception as exc:
            # Drop this one from the state so the next run retries rather than
            # swallowing an alert that was never actually delivered.
            next_state.pop(alert_fingerprint(alert), None)
            log.warning("queue_monitor: alert delivery failed (%s): %s", exc, message)
    _save_alert_state(next_state, path)
    return sent


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
    # Deliver, don't just log. Fail-soft: a broken notification channel must not turn a
    # monitoring run into a failed job.
    try:
        snapshot["delivered"] = dispatch_alerts(alerts)
    except Exception as exc:
        log.warning("queue_monitor: alert dispatch failed: %s", exc)
        snapshot["delivered"] = []
    return snapshot


if __name__ == "__main__":
    snapshot = run()
    print(json.dumps(snapshot, indent=2, default=str))
