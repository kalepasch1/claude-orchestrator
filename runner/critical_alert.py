#!/usr/bin/env python3
"""
critical_alert.py - evaluate hard critical conditions and dispatch a single alert.

The gap this closes: `alert_rules_engine.py` evaluates *orchestrator* metrics
(quarantine ratio, throughput, approval backlog) on its own 60s loop, and
`error_alerter.py` knows how to *deliver* an alert on three channels. Nothing
evaluated the two conditions that take the fleet down outright and are not
orchestrator metrics at all:

  * host disk usage above a hard ceiling - every runner writes worktrees,
    logs and node_modules to the same volume, so a full disk wedges all of
    them at once;
  * task error rate above a hard ceiling - a sustained failure fraction means
    the fleet is burning tokens producing nothing.

Both are level-based, not derivative-based, on purpose: the 2026-08-08 outage
documented in alert_rules_engine.py was invisible to a ratio-vs-previous-run
test while the absolute level was in free fall.

Delivery is delegated to `error_alerter.alert()` so cooldown deduplication,
severity mapping and the in-app/email/webhook fan-out are inherited rather
than reimplemented.

Conventions: module-level singleton, fail-soft, ORCH_ env vars, thread-safe.

Usage:
    import critical_alert
    critical_alert.trigger_critical_alert()          # evaluate + dispatch
    critical_alert.trigger_critical_alert(dry_run=True)  # evaluate only
    critical_alert.stats()
"""
import os
import shutil
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Hard ceilings. Named rather than inlined so they are fleet-pushable through
# fleet_control.py (ORCH_-prefixed keys carry no secrets).
DISK_CRITICAL_PCT = float(os.environ.get("ORCH_CRITICAL_DISK_PCT", "90"))
ERROR_RATE_CRITICAL = float(os.environ.get("ORCH_CRITICAL_ERROR_RATE", "0.05"))
ERROR_RATE_WINDOW_MIN = int(os.environ.get("ORCH_CRITICAL_ERROR_WINDOW_MIN", "60"))
# Below this many terminal tasks in the window, an error *rate* is noise:
# one failure out of three is 33% and means nothing.
ERROR_RATE_MIN_SAMPLE = int(os.environ.get("ORCH_CRITICAL_ERROR_MIN_SAMPLE", "20"))
DISK_PATH = os.environ.get("ORCH_CRITICAL_DISK_PATH", os.path.expanduser("~"))
ENABLED = os.environ.get("ORCH_CRITICAL_ALERTS_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)

_lock = threading.Lock()
_STATE = {
    "evaluations": 0,
    "conditions_met": 0,
    "dispatched": 0,
    "last_eval_ts": 0.0,
    "last_conditions": [],
}


def disk_usage_pct(path: str = "") -> float:
    """Percent of the volume holding `path` that is in use.

    Fail-soft: returns 0.0 when the path is missing or unreadable, so a probe
    failure can never itself page the owner.
    """
    try:
        usage = shutil.disk_usage(path or DISK_PATH)
        if usage.total <= 0:
            return 0.0
        return (usage.used / usage.total) * 100.0
    except Exception:
        return 0.0


def error_rate(window_minutes: int = 0) -> tuple:
    """Fraction of terminal tasks in the window that failed.

    Returns (rate, sample_size). Fail-soft: (0.0, 0) when the DB is
    unavailable, which is deliberately below every threshold - a database we
    cannot read is the queue monitor's problem, not a reason to fire a
    critical page from here.
    """
    window = window_minutes or ERROR_RATE_WINDOW_MIN
    try:
        import db

        rows = db.query(
            "SELECT "
            "  COUNT(*) FILTER (WHERE state IN ('FAILED','BLOCKED','QUARANTINED')) AS bad, "
            "  COUNT(*) AS total "
            "FROM tasks "
            "WHERE updated_at > now() - (%s || ' minutes')::interval "
            "  AND state IN ('DONE','MERGED','FAILED','BLOCKED','QUARANTINED')",
            (str(window),),
        )
        if not rows:
            return (0.0, 0)
        row = rows[0]
        bad = row["bad"] if isinstance(row, dict) else row[0]
        total = row["total"] if isinstance(row, dict) else row[1]
        bad = int(bad or 0)
        total = int(total or 0)
        if total <= 0:
            return (0.0, 0)
        return (bad / total, total)
    except Exception:
        return (0.0, 0)


def evaluate() -> list:
    """Evaluate every critical condition. Returns a list of breach dicts.

    An empty list means healthy. Never raises.
    """
    conditions = []

    pct = disk_usage_pct()
    if pct > DISK_CRITICAL_PCT:
        conditions.append({
            "pattern": "disk_full",
            "metric": "disk_usage_pct",
            "value": round(pct, 2),
            "threshold": DISK_CRITICAL_PCT,
            "detail": (
                f"Disk usage on {DISK_PATH} is {pct:.1f}% "
                f"(critical above {DISK_CRITICAL_PCT:.0f}%). Worktrees, logs and "
                f"node_modules share this volume; a full disk wedges every runner."
            ),
        })

    rate, sample = error_rate()
    if sample >= ERROR_RATE_MIN_SAMPLE and rate > ERROR_RATE_CRITICAL:
        conditions.append({
            "pattern": "test_failure",
            "metric": "error_rate",
            "value": round(rate, 4),
            "threshold": ERROR_RATE_CRITICAL,
            "detail": (
                f"Task error rate is {rate * 100:.1f}% over the last "
                f"{ERROR_RATE_WINDOW_MIN}m ({sample} terminal tasks), above the "
                f"{ERROR_RATE_CRITICAL * 100:.0f}% ceiling."
            ),
        })

    with _lock:
        _STATE["evaluations"] += 1
        _STATE["last_eval_ts"] = time.time()
        _STATE["last_conditions"] = [c["metric"] for c in conditions]
        _STATE["conditions_met"] += len(conditions)

    return conditions


def trigger_critical_alert(dry_run: bool = False) -> dict:
    """Evaluate the critical conditions and dispatch an alert for each breach.

    Returns a summary dict: {"conditions": [...], "dispatched": n, "enabled": bool}.
    Fail-soft: never raises, and returns dispatched=0 rather than propagating a
    delivery failure - alerting that crashes the caller is worse than alerting
    that silently degrades.
    """
    if not ENABLED:
        return {"conditions": [], "dispatched": 0, "enabled": False}

    conditions = evaluate()
    dispatched = 0

    for cond in conditions:
        try:
            import error_alerter

            if dry_run:
                continue
            if error_alerter.alert(
                cond["pattern"],
                project_id="",
                detail=cond["detail"],
                severity="critical",
            ):
                dispatched += 1
        except Exception:
            # Broad by convention (fail-soft), but never silent: a swallowed
            # delivery failure that leaves no trace is how an outage goes
            # unnoticed twice.
            sys.stderr.write(
                f"critical_alert: dispatch failed for {cond.get('metric')}; "
                f"fail-soft continue\n"
            )

    with _lock:
        _STATE["dispatched"] += dispatched

    return {
        "conditions": conditions,
        "dispatched": dispatched,
        "enabled": True,
    }


def stats() -> dict:
    """Return evaluation counters for operators and tests."""
    with _lock:
        return dict(_STATE)


def reset():
    """Clear counters (for testing)."""
    with _lock:
        _STATE.update({
            "evaluations": 0,
            "conditions_met": 0,
            "dispatched": 0,
            "last_eval_ts": 0.0,
            "last_conditions": [],
        })


if __name__ == "__main__":
    import json

    print(json.dumps(trigger_critical_alert(dry_run="--dry-run" in sys.argv), indent=2))
