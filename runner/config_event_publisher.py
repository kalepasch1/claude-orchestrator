#!/usr/bin/env python3
"""
config_event_publisher.py - Publish fleet_config changes to Supabase Realtime channel 'config/*'.

Fail-soft, secret-safe. Uses Supabase Realtime broadcast via PostgREST.

Environment / fleet_config knobs:
  ORCH_CONFIG_EVENTS_ENABLED - enable config event publishing (default true)
  SUPABASE_URL               - base URL for Supabase project
  SUPABASE_SERVICE_KEY        - service-role key for auth
"""
import os, sys, json, time, threading, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_SAFE_PREFIXES = ("ORCH_", "MAX_PARALLEL", "PER_TASK_GB", "RAM_FLOOR_GB", "RAM_",
                  "RELEASE_", "QUEUE_", "CONT_", "JANITOR_", "REMEDIATION_",
                  "DEFAULT_TEST_CMD", "TASK_TIMEOUT", "ENABLE_", "SESSION_",
                  "ACCOUNT_COOLDOWN", "MERGE_", "DEPLOY_", "INTEGRATE_", "COST_")
_DENY_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PWD", "CREDENTIAL")
_lock = threading.Lock()
_last_snapshot = {}


def _is_enabled():
    return os.environ.get("ORCH_CONFIG_EVENTS_ENABLED", "true").lower() in ("true", "1", "yes")


def _safe_key(k):
    ku = k.upper()
    if any(m in ku for m in _DENY_MARKERS):
        return False
    return any(ku.startswith(p) for p in _SAFE_PREFIXES)


def _broadcast(channel, event, payload):
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        return False
    url = f"{base}/realtime/v1/api/broadcast"
    body = json.dumps({"messages": [{"topic": f"realtime:{channel}",
                                      "event": event, "payload": payload}]}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status in (200, 201, 202)
    except Exception:
        return False


def detect_changes():
    global _last_snapshot
    changes = []
    try:
        rows = db.select("fleet_config", {"select": "key,value"}) or []
    except Exception:
        return []
    current = {}
    for row in rows:
        k, v = row.get("key"), row.get("value")
        if k and v is not None and _safe_key(k):
            current[k] = str(v)
    with _lock:
        for k, v in current.items():
            old = _last_snapshot.get(k)
            if old != v:
                changes.append({"key": k, "value": v, "old_value": old})
        for k in list(_last_snapshot.keys()):
            if k not in current:
                changes.append({"key": k, "value": None, "old_value": _last_snapshot[k]})
        _last_snapshot = current
    return changes


def publish_changes(changes=None):
    if not _is_enabled():
        return {"published": 0, "failed": 0, "changes": [], "enabled": False}
    if changes is None:
        changes = detect_changes()
    if not changes:
        return {"published": 0, "failed": 0, "changes": []}
    published, failed = 0, 0
    for change in changes:
        key = change["key"]
        payload = {"key": key, "value": change["value"],
                   "old_value": change.get("old_value"), "timestamp": time.time()}
        ok = _broadcast(f"config/{key}", "config_changed", payload)
        if ok:
            published += 1
        else:
            failed += 1
    return {"published": published, "failed": failed, "changes": changes}


def snapshot():
    with _lock:
        return dict(_last_snapshot)

def invalidate():
    global _last_snapshot
    with _lock:
        _last_snapshot = {}

def stats():
    with _lock:
        return {"snapshot_size": len(_last_snapshot)}


def run():
    try:
        result = publish_changes()
        if result.get("changes"):
            print(f"config_event_publisher: published {result['published']}, "
                  f"failed {result['failed']}, "
                  f"changes: {[c['key'] for c in result['changes']]}")
        return result
    except Exception as e:
        print(f"config_event_publisher: skipped ({e})")
        return {"published": 0, "failed": 0, "error": str(e)}


if __name__ == "__main__":
    run()
