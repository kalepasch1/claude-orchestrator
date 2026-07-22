#!/usr/bin/env python3
"""realtime_config.py — Real-time fleet configuration via Supabase polling.

Provides a lightweight config watcher that detects fleet_config changes
and applies them immediately, rather than waiting for the next full loop tick.

Uses a change-detection approach: hashes the current config state and
re-applies only when a change is detected. This is cheaper than full
Supabase Realtime websocket but gives near-instant config propagation
(poll interval configurable, default 5s).

Integration: call realtime_config.start() from the runner's main init,
or call realtime_config.poll() from the main loop for synchronous mode.
"""
import hashlib
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

POLL_INTERVAL_S = float(os.environ.get("ORCH_REALTIME_POLL_S", "5"))
_state = {"hash": "", "running": False, "last_apply": 0.0}
_lock = threading.Lock()

# Only these prefixes are applied (mirrors fleet_control.py safety list)
_SAFE_PREFIXES = ("ORCH_", "MAX_PARALLEL", "PER_TASK_GB", "RAM_FLOOR_GB", "RAM_",
                  "RELEASE_", "QUEUE_", "CONT_", "JANITOR_", "REMEDIATION_",
                  "DEFAULT_TEST_CMD", "TASK_TIMEOUT", "ENABLE_", "SESSION_",
                  "ACCOUNT_COOLDOWN", "MERGE_", "DEPLOY_", "INTEGRATE_", "COST_")
_DENY_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PWD", "CREDENTIAL")


def _safe_key(k):
    ku = k.upper()
    if any(m in ku for m in _DENY_MARKERS):
        return False
    return any(ku.startswith(p) for p in _SAFE_PREFIXES)


def _fetch_config():
    """Fetch all fleet_config rows, return sorted list of (key, value)."""
    try:
        rows = db.select("fleet_config", {"select": "key,value", "order": "key.asc"}) or []
        return [(r["key"], str(r.get("value", ""))) for r in rows if r.get("key")]
    except Exception:
        return []


def _config_hash(pairs):
    """Deterministic hash of config state for change detection."""
    raw = json.dumps(pairs, sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()


def poll():
    """Check for config changes and apply if detected. Returns count of keys applied."""
    pairs = _fetch_config()
    h = _config_hash(pairs)

    with _lock:
        if h == _state["hash"]:
            return 0
        _state["hash"] = h
        _state["last_apply"] = time.time()

    applied = 0
    for k, v in pairs:
        if _safe_key(k):
            os.environ[k] = v
            applied += 1

    if applied:
        print(f"realtime_config: applied {applied} config keys (hash={h[:8]})", flush=True)
    return applied


def _poll_loop():
    """Background thread loop."""
    while _state["running"]:
        try:
            poll()
        except Exception as e:
            print(f"realtime_config: poll error ({e})")
        time.sleep(POLL_INTERVAL_S)


def start():
    """Start background config polling thread. Idempotent."""
    with _lock:
        if _state["running"]:
            return
        _state["running"] = True
    t = threading.Thread(target=_poll_loop, daemon=True, name="realtime-config")
    t.start()
    print(f"realtime_config: started (poll every {POLL_INTERVAL_S}s)", flush=True)


def stop():
    """Stop background polling."""
    with _lock:
        _state["running"] = False


def stats():
    """Return current watcher state."""
    with _lock:
        return {
            "running": _state["running"],
            "last_hash": _state["hash"][:8] if _state["hash"] else "",
            "last_apply": _state["last_apply"],
            "poll_interval_s": POLL_INTERVAL_S,
        }


# ── Tests ────────────────────────────────────────────────────────────────────
import unittest
from unittest.mock import patch, MagicMock


class TestRealtimeConfig(unittest.TestCase):

    @patch("realtime_config._fetch_config", return_value=[("ORCH_FOO", "bar")])
    def test_poll_applies_safe_key(self, _fc):
        _state["hash"] = ""
        n = poll()
        self.assertEqual(n, 1)
        self.assertEqual(os.environ.get("ORCH_FOO"), "bar")

    @patch("realtime_config._fetch_config", return_value=[("SECRET_KEY", "bad")])
    def test_poll_rejects_unsafe_key(self, _fc):
        _state["hash"] = ""
        os.environ.pop("SECRET_KEY", None)
        poll()
        self.assertNotIn("SECRET_KEY", os.environ)

    @patch("realtime_config._fetch_config", return_value=[("ORCH_X", "1")])
    def test_no_reapply_on_same_hash(self, _fc):
        _state["hash"] = ""
        poll()
        h = _state["hash"]
        n = poll()
        self.assertEqual(n, 0)
        self.assertEqual(_state["hash"], h)

    def test_config_hash_deterministic(self):
        pairs = [("A", "1"), ("B", "2")]
        self.assertEqual(_config_hash(pairs), _config_hash(pairs))

    def test_config_hash_changes(self):
        self.assertNotEqual(_config_hash([("A", "1")]), _config_hash([("A", "2")]))

    def test_safe_key_allows_orch(self):
        self.assertTrue(_safe_key("ORCH_POLL_S"))

    def test_safe_key_blocks_secret(self):
        self.assertFalse(_safe_key("ORCH_SECRET_KEY"))

    def test_stats_returns_dict(self):
        s = stats()
        self.assertIn("running", s)
        self.assertIn("poll_interval_s", s)


if __name__ == "__main__":
    if "--test" in sys.argv:
        unittest.main(argv=["test_realtime_config"])
    else:
        print(json.dumps(stats(), indent=2, default=str))
