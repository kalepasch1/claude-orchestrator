#!/usr/bin/env python3
"""
alert_rules_engine.py – Configurable alerting for the monitoring dashboard.

Evaluates real-time orchestrator metrics against user-defined thresholds,
fires alerts via inbox notifications, and tracks alert state (firing,
resolved, silenced) to prevent notification fatigue.

Conventions: module-level singleton, fail-soft, ORCH_ env vars, thread-safe.
"""
import os, sys, json, datetime, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

EVAL_INTERVAL_SEC = int(os.environ.get("ORCH_ALERT_EVAL_SEC", "60"))
SILENCE_MINUTES = int(os.environ.get("ORCH_ALERT_SILENCE_MIN", "30"))

_lock = threading.Lock()
_STATE = {
    "rules": [],
    "firing": {},
    "resolved": 0,
    "evaluations": 0,
}

DEFAULT_RULES = [
    {
        "id": "high_quarantine_rate",
        "name": "High quarantine rate",
        "metric": "quarantine_ratio",
        "operator": "gt",
        "threshold": 0.3,
        "severity": "warning",
    },
    {
        "id": "queue_stall",
        "name": "Queue stalled",
        "metric": "throughput_1h",
        "operator": "lt",
        "threshold": 1,
        "severity": "critical",
    },
    {
        "id": "approval_backlog",
        "name": "Approval backlog growing",
        "metric": "pending_approvals",
        "operator": "gt",
        "threshold": 10,
        "severity": "warning",
    },
    {
        "id": "low_merge_rate",
        "name": "Low merge rate",
        "metric": "merge_rate_24h",
        "operator": "lt",
        "threshold": 5,
        "severity": "info",
    },
]


def _compare(value, operator, threshold):
    """Compare a metric value against a threshold using the given operator.

    Supported operators: gt, lt, gte, lte, eq.
    Returns False on type-conversion errors or unknown operators.
    """
    try:
        value = float(value)
        threshold = float(threshold)
    except (ValueError, TypeError):
        return False
    if operator == "gt":
        return value > threshold
    elif operator == "lt":
        return value < threshold
    elif operator == "gte":
        return value >= threshold
    elif operator == "lte":
        return value <= threshold
    elif operator == "eq":
        return value == threshold
    return False


def _collect_metrics():
    """Gather current orchestrator metrics for evaluation."""
    metrics = {}
    try:
        import db
        # Queue state counts
        rows = db.sql("SELECT state, count(*)::int AS cnt FROM tasks GROUP BY state") or []
        state_counts = {r["state"]: r["cnt"] for r in rows}
        total = sum(state_counts.values()) or 1
        metrics["quarantine_ratio"] = state_counts.get("QUARANTINED", 0) / total
        metrics["queued_count"] = state_counts.get("QUEUED", 0)
        metrics["running_count"] = state_counts.get("RUNNING", 0)

        # Throughput
        cutoff_1h = (datetime.datetime.utcnow() - datetime.timedelta(hours=1)).isoformat() + "Z"
        done_1h = db.select("tasks", {"select": "id", "state": "eq.DONE", "updated_at": f"gte.{cutoff_1h}"}) or []
        metrics["throughput_1h"] = len(done_1h)

        cutoff_24h = (datetime.datetime.utcnow() - datetime.timedelta(hours=24)).isoformat() + "Z"
        merged_24h = db.select("tasks", {"select": "id", "state": "eq.MERGED", "updated_at": f"gte.{cutoff_24h}"}) or []
        metrics["merge_rate_24h"] = len(merged_24h)

        metrics["pending_approvals"] = state_counts.get("PENDING_REVIEW", 0)
    except Exception:
        pass
    return metrics


def evaluate(rules=None, metrics=None):
    """
    Evaluate alert rules against current metrics.

    Returns list of alert events (fired/resolved).
    """
    if rules is None:
        rules = DEFAULT_RULES
    if metrics is None:
        metrics = _collect_metrics()

    now = datetime.datetime.utcnow().isoformat() + "Z"
    events = []

    with _lock:
        for rule in rules:
            rule_id = rule["id"]
            value = metrics.get(rule["metric"])
            if value is None:
                continue

            is_firing = _compare(value, rule["operator"], rule["threshold"])
            was_firing = rule_id in _STATE["firing"]

            if is_firing and not was_firing:
                # New alert
                alert = {
                    "rule_id": rule_id,
                    "name": rule["name"],
                    "severity": rule["severity"],
                    "event": "firing",
                    "metric": rule["metric"],
                    "value": value,
                    "threshold": rule["threshold"],
                    "fired_at": now,
                }
                _STATE["firing"][rule_id] = alert
                events.append(alert)

            elif not is_firing and was_firing:
                # Alert resolved
                prev = _STATE["firing"].pop(rule_id)
                events.append({
                    "rule_id": rule_id,
                    "name": rule["name"],
                    "event": "resolved",
                    "fired_at": prev.get("fired_at"),
                    "resolved_at": now,
                })
                _STATE["resolved"] += 1

        _STATE["evaluations"] += 1

    # Persist firing alerts
    for event in events:
        if event["event"] == "firing":
            try:
                import db
                db.insert("inbox", {
                    "kind": "alert",
                    "title": f"[{event['severity'].upper()}] {event['name']}: "
                             f"{event['metric']}={event['value']}",
                    "body": json.dumps(event, indent=2, default=str)[:3000],
                    "created_at": now,
                })
            except Exception:
                pass

    return events


def firing_alerts():
    """Return currently firing alerts."""
    with _lock:
        return list(_STATE["firing"].values())


def silence(rule_id, minutes=None):
    """Silence a specific alert rule for N minutes."""
    if minutes is None:
        minutes = SILENCE_MINUTES
    with _lock:
        if rule_id in _STATE["firing"]:
            _STATE["firing"][rule_id]["silenced_until"] = (
                datetime.datetime.utcnow() + datetime.timedelta(minutes=minutes)
            ).isoformat() + "Z"
            return True
    return False


def stats():
    with _lock:
        return {
            "firing": len(_STATE["firing"]),
            "resolved": _STATE["resolved"],
            "evaluations": _STATE["evaluations"],
        }


def run():
    """Entry point for periodic jobs."""
    events = evaluate()
    return {"events": len(events), "firing": len(firing_alerts())}


if __name__ == "__main__":
    print(json.dumps({"firing": firing_alerts(), "stats": stats()}, indent=2))
