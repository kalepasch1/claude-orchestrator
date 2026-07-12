#!/usr/bin/env python3
"""
error_monitor.py - Real-time error monitoring and alerting.

Watches task outcomes and error patterns in real time, alerting operators
when error rates spike or specific critical error classes appear.

Usage:
    import error_monitor
    error_monitor.record_error(task_id, slug, error_class, note)
    error_monitor.check_and_alert()

Alerts are written to fleet_config as ORCH_ALERT_* keys.

Env:
    ORCH_ERROR_MONITOR_ENABLED  (default "true")
    ORCH_ALERT_WINDOW_SEC       (default "300")
    ORCH_ALERT_THRESHOLD        (default "5")
    ORCH_CRITICAL_CLASSES       (default "permission_error,exhaustion")
"""
import os, sys, time, threading, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ENABLED = os.environ.get("ORCH_ERROR_MONITOR_ENABLED", "true").lower() in ("true", "1")
_WINDOW = int(os.environ.get("ORCH_ALERT_WINDOW_SEC", "300"))
_THRESHOLD = int(os.environ.get("ORCH_ALERT_THRESHOLD", "5"))
_CRITICAL = set(os.environ.get("ORCH_CRITICAL_CLASSES", "permission_error,exhaustion").split(","))

_lock = threading.Lock()
_recent_errors: list = []
_last_alert_time: float = 0.0
_ALERT_COOLDOWN = 120


def record_error(task_id: str, slug: str, error_class: str, note: str = "") -> None:
    """Record an error event for monitoring. Fail-soft."""
    if not _ENABLED:
        return
    try:
        now = time.time()
        with _lock:
            _recent_errors.append((now, task_id, error_class, note[:200]))
            cutoff = now - _WINDOW
            while _recent_errors and _recent_errors[0][0] < cutoff:
                _recent_errors.pop(0)
    except Exception:
        pass


def _write_alert(alert_key: str, message: str) -> None:
    """Write alert to fleet_config. Fail-soft."""
    try:
        import db
        db.upsert("fleet_config", {"key": alert_key, "value": json.dumps({
            "message": message, "timestamp": time.time(),
        })}, on_conflict="key")
    except Exception:
        pass


def check_and_alert() -> dict:
    """Check recent errors against thresholds and fire alerts.
    Returns {ok, error_count, alerts_fired}. Fail-soft."""
    if not _ENABLED:
        return {"ok": True, "error_count": 0, "alerts_fired": []}
    try:
        global _last_alert_time
        now = time.time()
        alerts_fired = []
        with _lock:
            cutoff = now - _WINDOW
            while _recent_errors and _recent_errors[0][0] < cutoff:
                _recent_errors.pop(0)
            current = list(_recent_errors)
        error_count = len(current)
        if error_count >= _THRESHOLD and (now - _last_alert_time) > _ALERT_COOLDOWN:
            classes = {}
            for _, _, ec, _ in current:
                classes[ec] = classes.get(ec, 0) + 1
            _write_alert("ORCH_ALERT_ERROR_SPIKE",
                         f"Error spike: {error_count} errors in {_WINDOW}s. Classes: {classes}")
            alerts_fired.append("error_spike")
            _last_alert_time = now
        for ts, tid, ec, note in current:
            if ec in _CRITICAL and ts > _last_alert_time - _ALERT_COOLDOWN:
                _write_alert(f"ORCH_ALERT_CRITICAL_{ec.upper()}",
                             f"Critical '{ec}' on task {tid}: {note[:100]}")
                if "critical" not in alerts_fired:
                    alerts_fired.append("critical")
        return {"ok": error_count < _THRESHOLD, "error_count": error_count,
                "alerts_fired": alerts_fired}
    except Exception:
        return {"ok": True, "error_count": 0, "alerts_fired": []}


def stats() -> dict:
    """Return current monitoring state."""
    with _lock:
        return {"recent_count": len(_recent_errors), "window_sec": _WINDOW,
                "threshold": _THRESHOLD, "enabled": _ENABLED}
