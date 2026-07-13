#!/usr/bin/env python3
"""
fleet_control.py - the Mac-1 <-> Mac-2 (N-machine) coordination gateway.

Both runners already share one Supabase queue; this closes the last siloed gaps so you configure the
WHOLE fleet from one place (Mission Control / the DB) and never touch a second machine's terminal:

  1. CENTRAL CONFIG  - `fleet_config` (key/value) is loaded into env every loop on EVERY machine. Change
     MAX_PARALLEL / ORCH_EXTRA_CODERS / model policy / any ORCH_* knob once here and both Macs converge.
     Only safe config keys are applied (never secrets/keys/tokens).
  2. CENTRAL CONTROL - `fleet_control` rows (action: restart | git_pull | reload_config | pause | resume;
     target: hostname or 'all') are honored by the targeted machine(s), each acking into handled_by.
     Restart, pull-and-restart, or pause/resume a single Mac or the whole fleet from the cockpit — no
     ssh, no second terminal. pause is a soft, keepalive-safe stop: the runner stops claiming new work
     but stays resident (a hard launchd stop would fight keepalive and be un-resumable remotely), and
     resume lifts it on the next loop. Implemented via kill_switch's host scope.
  3. AUTO-UPDATE     - with ORCH_AUTO_PULL=true, each machine periodically `git pull --ff-only`, so a push
     from Mac 1 propagates to every machine automatically (no "now go run it on Mac 2 too").

Pure DB + git; no model spend. Fail-soft: any error is swallowed so it can never wedge the runner.
"""
import os, sys, time, socket, subprocess, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import kill_switch

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


def _current_branch():
    return _git("branch", "--show-current").stdout.strip()


def _has_upstream():
    return _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").returncode == 0


def _dirty_worktree():
    # Only TRACKED modifications should block auto-pull. Untracked files (stray build caches,
    # logs, generated test artifacts) do NOT prevent a --ff-only pull — git itself refuses only
    # if an incoming file would overwrite an untracked one. Counting untracked files here (plain
    # `status --porcelain` lists them as `??`) permanently disabled auto-pull on any clone that
    # had a single leftover file, which is what kept machines chronically stale despite
    # ORCH_AUTO_PULL=true. Exclude untracked so a --ff-only pull can proceed.
    return bool(_git("status", "--porcelain", "--untracked-files=no").stdout.strip())


def _pull_safe():
    branch = _current_branch()
    if not branch:
        return False, "detached HEAD"
    if branch.startswith("agent/"):
        return False, f"agent branch {branch}"
    if not _has_upstream():
        return False, f"branch {branch} has no upstream"
    if _dirty_worktree():
        return False, "dirty worktree"
    return True, branch


def _host_aliases():
    aliases = {HOST}
    if HOST.endswith(".local"):
        aliases.add(HOST[:-6])
    else:
        aliases.add(HOST + ".local")
    return aliases


def _target_matches(target):
    return target == "all" or target in _host_aliases()


def _control_done(target, handled, params):
    if target != "all":
        return True
    expected = set((params or {}).get("expected_hosts") or [])
    if not expected:
        return False
    return expected.issubset(set(handled or []))


def _restart():
    """Exit; keepalive.sh respawns a fresh runner with new code/config.

    Do not unlink runner.lock here. The running process holds an flock on that file; deleting it
    creates a new inode that another supervisor can lock before this process exits, causing two
    runners to operate on the same machine. Exiting naturally releases the existing flock.
    """
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
        ok, reason = _pull_safe()
        if not ok:
            print(f"fleet_control: auto-pull skipped ({reason})", flush=True)
            return False
        before = _git("rev-parse", "HEAD").stdout.strip()
        pulled = _git("pull", "--ff-only")
        if pulled.returncode != 0:
            msg = (pulled.stderr or pulled.stdout or "git pull failed").strip()
            raise RuntimeError(msg[-500:])
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
        aliases = _host_aliases()
        if not _target_matches(target) or any(h in handled for h in aliases):
            continue
        action = str(r.get("action") or "").lower()
        try:
            if action == "reload_config":
                load_config()
            elif action == "git_pull":
                ok, reason = _pull_safe()
                if not ok:
                    raise RuntimeError(f"git_pull unsafe: {reason}")
                pulled = _git("pull", "--ff-only")
                if pulled.returncode != 0:
                    msg = (pulled.stderr or pulled.stdout or "git pull failed").strip()
                    raise RuntimeError(msg[-500:])
            elif action == "restart":
                pass
            elif action == "pause":
                # soft, keepalive-safe: the runner's claim loop honors this host-scoped
                # pause (kill_switch.is_paused) and stops claiming without exiting.
                reason = str((r.get("params") or {}).get("reason") or "fleet pause")
                kill_switch.pause(scope="host", project=HOST, reason=reason, by="fleet_control")
            elif action == "resume":
                kill_switch.resume(scope="host", project=HOST, by="fleet_control")
            else:
                raise RuntimeError(f"unknown fleet action: {action}")
            # ack this host
            new_handled = list(dict.fromkeys(handled + [HOST]))
            params = r.get("params") or {}
            db.update("fleet_control", {"id": r["id"]},
                      {
                          "handled_by": new_handled,
                          "done": _control_done(target, new_handled, params),
                          "last_error": None,
                          "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      })
            done += 1
            if action == "git_pull" and params.get("restart", True):
                _restart()
            if action == "restart":
                _restart()
        except Exception as e:
            print(f"fleet_control: action '{action}' failed on {HOST}: {e}")
            try:
                db.update("fleet_control", {"id": r["id"]}, {
                    "attempts": int(r.get("attempts") or 0) + 1,
                    "last_error": str(e)[:1000],
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                })
            except Exception:
                pass
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
