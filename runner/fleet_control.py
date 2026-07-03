#!/usr/bin/env python3
"""
fleet_control.py - the Mac-1 <-> Mac-2 (N-machine) coordination gateway.

Both runners already share one Supabase queue; this closes the last siloed gaps so you configure the
WHOLE fleet from one place (Mission Control / the DB) and never touch a second machine's terminal:

  1. CENTRAL CONFIG  - `fleet_config` (key/value) is loaded into env every loop on EVERY machine. Change
     MAX_PARALLEL / ORCH_EXTRA_CODERS / model policy / any ORCH_* knob once here and both Macs converge.
     Only safe config keys are applied (never secrets/keys/tokens).
  2. CENTRAL CONTROL - `fleet_control` rows (action: restart | git_pull | reload_config; target: hostname
     or 'all') are honored by the targeted machine(s), each acking into handled_by. Restart or pull-and-
     restart the whole fleet from the cockpit — no ssh, no second terminal.
  3. AUTO-UPDATE     - with ORCH_AUTO_PULL=true, each machine periodically `git pull --ff-only`, so a push
     from Mac 1 propagates to every machine automatically (no "now go run it on Mac 2 too").

Pure DB + git; no model spend. Fail-soft: any error is swallowed so it can never wedge the runner.
"""
import os, sys, time, socket, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = socket.gethostname()
_last_pull = {"t": 0.0}

# only these config keys may be pushed fleet-wide (never secrets). Anything containing a credential
# marker is rejected outright.
_SAFE_PREFIXES = ("ORCH_", "MAX_PARALLEL", "PER_TASK_GB", "RAM_FLOOR_GB", "RAM_", "RELEASE_", "QUEUE_",
                  "CONT_", "JANITOR_", "REMEDIATION_", "DEFAULT_TEST_CMD", "TASK_TIMEOUT", "ENABLE_",
                  "SESSION_", "ACCOUNT_COOLDOWN", "MERGE_", "DEPLOY_", "INTEGRATE_", "COST_")
_DENY_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PWD", "CREDENTIAL")


def _safe_key(k):
    ku = k.upper()
    if any(m in ku for m in _DENY_MARKERS):
        return False
    return any(ku.startswith(p) for p in _SAFE_PREFIXES)


def load_config():
    """Apply central fleet_config into this process's env (safe keys only)."""
    n = 0
    try:
        for row in (db.select("fleet_config", {"select": "key,value"}) or []):
            k, v = row.get("key"), row.get("value")
            if k and v is not None and _safe_key(k):
                os.environ[k] = str(v)
                n += 1
    except Exception:
        pass
    return n


def _git(*args, timeout=120):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, timeout=timeout)


def _restart():
    """Release the singleton lock and exit; keepalive.sh respawns a fresh runner with new code/config."""
    try:
        lock = os.path.join(REPO, ".runtime", "runner.lock")
        if os.path.exists(lock):
            os.remove(lock)
    except Exception:
        pass
    print(f"fleet_control: restart requested — exiting for keepalive respawn ({HOST})", flush=True)
    os._exit(0)


def self_update():
    """Periodic git pull so every machine tracks the pushed code without manual per-Mac steps."""
    if os.environ.get("ORCH_AUTO_PULL", "false").lower() not in ("true", "1", "yes"):
        return False
    interval = float(os.environ.get("ORCH_AUTO_PULL_MIN", "5")) * 60
    if time.time() - _last_pull["t"] < interval:
        return False
    _last_pull["t"] = time.time()
    try:
        before = _git("rev-parse", "HEAD").stdout.strip()
        _git("pull", "--ff-only")
        after = _git("rev-parse", "HEAD").stdout.strip()
        if before and after and before != after:
            print(f"fleet_control: auto-pulled {before[:8]}->{after[:8]} on {HOST}", flush=True)
            if os.environ.get("ORCH_AUTO_PULL_RESTART", "true").lower() in ("true", "1", "yes"):
                _restart()
            return True
    except Exception as e:
        print(f"fleet_control: auto-pull failed ({e})")
    return False


def process_controls():
    """Honor control actions targeted at this host (or 'all')."""
    done = 0
    try:
        rows = db.select("fleet_control", {"select": "*", "done": "eq.false",
                                           "order": "requested_at.asc", "limit": "50"}) or []
    except Exception:
        return 0
    for r in rows:
        target = str(r.get("target") or "all")
        handled = r.get("handled_by") or []
        if target not in ("all", HOST) or HOST in handled:
            continue
        action = str(r.get("action") or "").lower()
        try:
            if action == "reload_config":
                load_config()
            elif action == "git_pull":
                _git("pull", "--ff-only")
            # ack this host
            db.update("fleet_control", {"id": r["id"]},
                      {"handled_by": handled + [HOST], "done": (target == HOST)})
            done += 1
            if action == "git_pull" and (r.get("params") or {}).get("restart", True):
                _restart()
            if action == "restart":
                _restart()
        except Exception as e:
            print(f"fleet_control: action '{action}' failed on {HOST}: {e}")
    return done


def tick():
    """One coordination cycle — call from the main loop and/or the scheduler. Fail-soft."""
    try:
        load_config()
        process_controls()
        self_update()
    except Exception as e:
        print(f"fleet_control: tick error ({e})")


if __name__ == "__main__":
    print(f"fleet_control on {HOST}: config-keys={load_config()}, controls={process_controls()}")
