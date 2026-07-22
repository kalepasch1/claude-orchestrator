#!/usr/bin/env python3
"""Local DB health breaker/status helpers.

Supabase can be unavailable while the runner is otherwise healthy. These helpers keep a
small local status file so the dashboard/autopilot can show a clear breaker instead of
silently retrying or looking idle.
"""
import datetime
import json
import os
import tempfile
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RUNTIME = os.path.join(ROOT, ".runtime")
STATUS_FILE = os.path.join(RUNTIME, "db_health.json")


def _now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _error_payload(error):
    code = getattr(error, "code", None)
    reason = getattr(error, "reason", None)
    if isinstance(error, urllib.error.HTTPError):
        code = error.code
        reason = error.reason
    return {
        "type": type(error).__name__,
        "message": str(error)[:500],
        "http_status": code,
        "reason": str(reason or "")[:240],
    }


def _atomic_write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".db-health.", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def read():
    try:
        with open(STATUS_FILE) as f:
            return json.load(f)
    except Exception:
        return {
            "ok": None,
            "status": "unknown",
            "last_checked": None,
            "source": "local",
        }


def record(ok, source, error=None, extra=None):
    payload = {
        "ok": bool(ok),
        "status": "ok" if ok else "down",
        "source": source,
        "last_checked": _now(),
    }
    if error is not None:
        payload["error"] = _error_payload(error)
    if extra:
        payload.update(extra)
    _atomic_write(STATUS_FILE, payload)
    return payload


def probe(source="probe", check=None):
    """Run a cheap DB check and update the local breaker file."""
    if check is None:
        def check():
            import db
            return db.select("projects", {"select": "id", "limit": "1"})
    try:
        check()
        return record(True, source)
    except Exception as e:
        return record(False, source, e)

