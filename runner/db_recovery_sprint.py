#!/usr/bin/env python3
from __future__ import annotations
"""Run a drain sprint immediately after an authenticated Supabase outage clears."""
import datetime
import json
import os
import subprocess
import sys
import time

# Recovery probing must not inherit the normal long Supabase timeout. During an
# origin-down event this job runs frequently, so use a short no-retry breaker and
# let the next interval try again.
os.environ.setdefault("ORCH_SUPABASE_TIMEOUT", os.environ.get("ORCH_DB_RECOVERY_TIMEOUT", "12"))
os.environ.setdefault("ORCH_SUPABASE_RETRIES", os.environ.get("ORCH_DB_RECOVERY_RETRIES", "0"))

import db


RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(RUNNER_DIR)
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.join(REPO_ROOT, ".runtime"))
STATE = os.path.join(HOME, "db_recovery_sprint.json")
HEALTH = os.path.join(HOME, "db_health.json")
LOCK = os.path.join(HOME, "db_recovery_sprint.lock")
MIN_SPRINT_INTERVAL_S = int(os.environ.get("ORCH_DB_RECOVERY_SPRINT_INTERVAL_S", "900"))
_LOCK_FD = None


def _now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _read_state():
    try:
        with open(STATE) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def _acquire_lock():
    global _LOCK_FD
    try:
        import fcntl
        os.makedirs(os.path.dirname(LOCK), exist_ok=True)
        _LOCK_FD = open(LOCK, "a+")
        fcntl.flock(_LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _LOCK_FD.seek(0)
        _LOCK_FD.truncate()
        _LOCK_FD.write(str(os.getpid()))
        _LOCK_FD.flush()
        return True
    except Exception:
        return False


def _probe_db():
    try:
        db.select("projects", {"select": "id", "limit": "1"})
        return {"ok": True, "status": "ok", "checked_at": _now()}
    except Exception as e:
        return {"ok": False, "status": "down", "checked_at": _now(), "error": str(e)[:240]}


def _run(label, cmd, timeout):
    started = time.time()
    try:
        res = subprocess.run(cmd, cwd=RUNNER_DIR, env=os.environ.copy(),
                             text=True, capture_output=True, timeout=timeout)
        return {
            "label": label,
            "ok": res.returncode == 0,
            "code": res.returncode,
            "seconds": round(time.time() - started, 1),
            "stdout": (res.stdout or "")[-1200:],
            "stderr": (res.stderr or "")[-1200:],
        }
    except Exception as e:
        return {"label": label, "ok": False, "seconds": round(time.time() - started, 1),
                "error": str(e)[:400]}


def run(force=False):
    if not _acquire_lock():
        print("db_recovery_sprint: another recovery sprint is already running")
        return {"ran": False, "skipped": "locked"}
    state = _read_state()
    probe = _probe_db()
    _write_json(HEALTH, {**probe, "source": "db_recovery_sprint"})
    if not probe["ok"]:
        state.update({"last_down_at": probe["checked_at"], "last_error": probe.get("error")})
        _write_json(STATE, state)
        print(f"db_recovery_sprint: DB down ({probe.get('error')})")
        return {"db": probe, "ran": False}

    last_sprint = float(state.get("last_sprint_ts") or 0)
    recovered = bool(state.get("last_down_at")) and state.get("last_recovered_at") != state.get("last_down_at")
    due = (time.time() - last_sprint) >= MIN_SPRINT_INTERVAL_S
    if not force and not (recovered and due):
        print("db_recovery_sprint: DB ok; no recovery sprint due")
        return {"db": probe, "ran": False}

    jobs = [
        ("intake_watcher", [sys.executable, os.path.join(RUNNER_DIR, "intake_watcher.py")], 180),
        ("queue_janitor", [sys.executable, os.path.join(RUNNER_DIR, "queue_janitor.py")], 180),
        ("task_dedup", [sys.executable, os.path.join(RUNNER_DIR, "task_dedup.py")], 180),
        ("prewarm", [sys.executable, os.path.join(RUNNER_DIR, "prewarm.py")], 240),
        ("merge_train", [sys.executable, os.path.join(RUNNER_DIR, "merge_train.py")], 420),
        ("release_train", [sys.executable, os.path.join(RUNNER_DIR, "release_train.py")], 600),
        ("deploy_verify", [sys.executable, os.path.join(RUNNER_DIR, "deploy_verify.py")], 240),
        ("autopilot", [sys.executable, os.path.join(RUNNER_DIR, "autopilot.py")], 240),
    ]
    results = [_run(label, cmd, timeout) for label, cmd, timeout in jobs]
    state.update({
        "last_recovered_at": state.get("last_down_at") or probe["checked_at"],
        "last_sprint_at": _now(),
        "last_sprint_ts": time.time(),
        "last_results": results,
    })
    _write_json(STATE, state)
    print(json.dumps({"db": probe, "ran": True, "results": results}, indent=2, default=str))
    return {"db": probe, "ran": True, "results": results}


if __name__ == "__main__":
    run(force="--force" in sys.argv)
