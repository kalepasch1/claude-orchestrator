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
    # ---- Integration throughput: ABSOLUTE, LEVEL-BASED triggers ----------------
    #
    # The 2026-08-08 outage. Merges per day: Aug 5 = 234, Aug 6 = 246, Aug 7 = 45,
    # Aug 8 = 4. A 60x collapse from peak; the fleet shipped essentially nothing for
    # ~36h. Two independent reasons nothing responded:
    #
    #   * the repair loop only fires a playbook when a KPI is >2x worse than the
    #     PREVIOUS run. That is a derivative test and it is blind to a slow
    #     catastrophe — the loop's own stored baseline saw merged_24h 15 -> 9, a
    #     ratio of 1.667, under its 2x bar, while the real level was in free fall;
    #   * the only absolute rule here, `low_merge_rate`, fired at `< 5` with severity
    #     "info". Aug 7's 45 merges tripped nothing at all, and Aug 8's 4 merges
    #     produced an "info" — the single most business-critical failure the fleet
    #     has, ranked below queue depth.
    #
    # So: a LADDER of absolute levels, and a severity that matches the stakes. A level
    # test cannot be outrun by a gradual decline, however smooth.
    {
        "id": "merge_throughput_degraded",
        "name": "Merge throughput degraded",
        "metric": "merge_rate_24h",
        "operator": "lt",
        # Aug 7 (45 merges) would have fired here, ~24h before the fleet hit zero.
        "threshold": 50,
        "severity": "warning",
    },
    {
        "id": "merge_throughput_collapsed",
        "name": "Merge throughput collapsed — the fleet is not shipping",
        "metric": "merge_rate_24h",
        "operator": "lt",
        "threshold": 10,
        # Critical, not info: nothing merging is worse than a deep queue.
        "severity": "critical",
    },
    {
        "id": "merge_stall_1h",
        "name": "No merges in the last hour",
        "metric": "merge_rate_1h",
        "operator": "lt",
        "threshold": 1,
        # Fast detection. A 24h window needs most of a day of zero before it reads
        # as zero; the outage ran 7.5h before anyone looked.
        "severity": "critical",
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

        # Short window so a stall is visible in an hour rather than a day. A 24h
        # counter still reads 60 the morning after everything stopped.
        merged_1h = db.select("tasks", {"select": "id", "state": "eq.MERGED",
                                        "updated_at": f"gte.{cutoff_1h}"}) or []
        metrics["merge_rate_1h"] = len(merged_1h)

        metrics["pending_approvals"] = state_counts.get("PENDING_REVIEW", 0)
    except Exception as e:
        # Was `pass`. Silence here is the worst possible failure of a monitor: with no
        # metrics every `lt` rule evaluates against None, `_compare` returns False, and
        # the dashboard shows a calm green board precisely when the control plane is
        # unreachable. Say so, out loud, and still fail soft.
        print(f"[alert_rules_engine] metric collection FAILED ({type(e).__name__}: {e}); "
              f"alerts evaluated on partial metrics — a quiet board is NOT evidence of health",
              file=sys.stderr)
        metrics["_collection_error"] = f"{type(e).__name__}: {e}"
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
            except Exception as e:
                # Was `pass`. An alert that cannot be persisted is exactly when someone
                # needs to hear about it; swallowing the error silently loses both the
                # alert and the fact that alerting is broken.
                print(f"[alert_rules_engine] could not persist alert {event['rule_id']}: "
                      f"{type(e).__name__}: {e}", file=sys.stderr)
            dispatch_critical(event)

    return events


def dispatch_critical(event, notifier=None):
    """Send CRITICAL alerts to the real notification channel. Returns True if sent.

    An inbox row is a record, not a notification — nothing pages on it, and the row is
    only seen by someone already looking at the dashboard. That is the same failure the
    fleet keeps hitting: "production stopped and NOTHING reported a failure". A rule
    marked `critical` has to leave the database.

    Deliberately CRITICAL only. Routing warnings here too is how a channel becomes noise
    and then gets muted, which is worse than not having it — `queue_stall` and
    `merge_throughput_collapsed` are the ones worth waking someone for.

    Fail-soft, and loudly: a notifier that raises must not break the evaluation loop that
    produced the alert, but it must not disappear either.
    """
    try:
        # Normalize FIRST. A non-dict event reaching the error handler made the handler
        # itself raise (`'str' object has no attribute 'get'`), turning a fail-soft path
        # into the exception it existed to prevent.
        if not isinstance(event, dict):
            return False
        if event.get("event") != "firing":
            return False
        if str(event.get("severity", "")).lower() != "critical":
            return False
        if notifier is None:
            import notify as _notify
            notifier = _notify.send
        notifier(
            f"[CRITICAL] {event.get('name')}: {event.get('metric')}={event.get('value')} "
            f"(threshold {event.get('threshold')})")
        return True
    except Exception as e:
        rule_id = event.get("rule_id") if isinstance(event, dict) else "<malformed>"
        print(f"[alert_rules_engine] critical dispatch failed for "
              f"{rule_id}: {type(e).__name__}: {e}", file=sys.stderr)
        return False


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
