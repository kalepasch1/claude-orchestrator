#!/usr/bin/env python3
"""
lane_guard.py - hard wall-clock + heartbeat limits on agentic-coder lanes.

ROOT CAUSE (operator incident 2026-08-02): 64 of 66 headless coder lanes were
zombies >1h old. The fleet was "full of dead workers", pinning ALL RAM and every
slot; the runner mem-gate then correctly refused new claims (claimable=803,
claiming ~0), so the visible symptom was a stalled queue and the actual fault was
undead lanes.

Why the existing timeout did not stop it: agentic_coders.run() used

    subprocess.run(["bash", "-lc", cmd], timeout=timeout)

On TimeoutExpired, Python kills the DIRECT CHILD only -- the `bash -lc` wrapper.
The grandchild it spawned (`claude --output-format ...`, or aider) is reparented
to init and keeps running, holding its RAM forever. Every timeout therefore
*created* a zombie instead of reaping one, and nothing in the fleet ever
collected them. lane_medic.sh was written as a stopgap that hunts these orphans
by `ps` afterwards; this module removes the need to create them.

The fix is process GROUPS: start each lane with start_new_session=True so it
becomes a process-group leader, then signal the whole group. A grandchild cannot
outlive its lane unless it deliberately escapes its process group.

Two independent limits, because they catch different failures:

  wall-clock  a lane that is working but will never finish in a useful time.
              Per task class, default 45m.
  idle        a lane that is wedged RIGHT NOW -- no output for N minutes. Catches
              a hung API socket or an interactive prompt in minutes rather than
              waiting out the full wall-clock budget. This is the "lane without a
              live heartbeat is killed earlier" requirement.

Fail-soft throughout: any internal error returns a result dict, never raises.
A bug in the reaper must not wedge the runner it protects.
"""
import os
import signal
import subprocess
import sys
import tempfile
import time

NAME = "lane-guard"

# 45m default per the operator directive. Classes that are meant to be quick get
# tighter budgets -- a 45m canary is already a failure, waiting the full budget
# only converts it into a slot that is unavailable for 45m.
DEFAULT_LANE_TIMEOUT_S = int(os.environ.get("ORCH_LANE_TIMEOUT_DEFAULT", "2700"))
CLASS_TIMEOUTS = {
    "canary": 900,
    "toolchain-repair": 1800,
    "bugfix": 2400,
    "qafix": 2400,
    "build": 2700,
    "recovery": 2700,
    "legal": 3600,
}

# No output at all for this long => wedged, not working.
DEFAULT_IDLE_TIMEOUT_S = int(os.environ.get("ORCH_LANE_IDLE_TIMEOUT", "600"))

# Grace between SIGTERM and SIGKILL: let the coder flush a partial diff.
KILL_GRACE_S = float(os.environ.get("ORCH_LANE_KILL_GRACE", "5"))

POLL_S = float(os.environ.get("ORCH_LANE_POLL", "0.5"))

ENABLED = os.environ.get("ORCH_LANE_GUARD_ENABLED", "true").lower() in (
    "1", "true", "yes", "on")


def guard_or_exit(name, interval_s=None):
    """Acquire the cross-process interval guard or exit this duplicate cleanly."""
    try:
        import single_instance
        owned, timer = single_instance.guard(name, interval_s=interval_s)
        if not owned:
            print(f"{NAME}: {name} already running; duplicate tick skipped", flush=True)
            raise SystemExit(0)
        return timer
    except SystemExit:
        raise
    except Exception:
        # A broken guard must not silently disable a periodic safety job forever.
        return None

def timeout_for(task_class, default=None):
    """Wall-clock budget in seconds for a task class.

    Precedence: ORCH_LANE_TIMEOUT_<CLASS> env > CLASS_TIMEOUTS > default.
    Unknown/None class falls back to the default rather than to "no limit" --
    an unrecognised class is exactly the case that must not run unbounded.
    """
    fallback = int(default) if default else DEFAULT_LANE_TIMEOUT_S
    key = str(task_class or "").strip().lower()
    if not key:
        return fallback
    env_key = "ORCH_LANE_TIMEOUT_" + key.replace("-", "_").upper()
    raw = os.environ.get(env_key)
    if raw:
        try:
            v = int(raw)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    return int(CLASS_TIMEOUTS.get(key, fallback))


def kill_process_group(pid, grace=None):
    """SIGTERM the process GROUP led by pid, SIGKILL survivors after `grace`.

    Signalling the group -- not the pid -- is the whole point: the lane's real
    work happens in a grandchild, and killing only `pid` is what produced the
    orphan fleet. Returns a small dict describing what happened; never raises.
    """
    grace = KILL_GRACE_S if grace is None else grace
    out = {"pid": pid, "termed": False, "killed": False, "error": ""}
    if not pid:
        return out
    try:
        pgid = os.getpgid(pid)
    except Exception as e:
        out["error"] = f"getpgid: {e}"
        return out
    # Refuse to signal our OWN group -- that would take down the runner itself.
    try:
        if pgid == os.getpgid(0):
            out["error"] = "refusing to signal the runner's own process group"
            return out
    except Exception:
        pass
    try:
        os.killpg(pgid, signal.SIGTERM)
        out["termed"] = True
    except ProcessLookupError:
        return out
    except Exception as e:
        out["error"] = f"sigterm: {e}"
    deadline = time.time() + max(0.0, grace)
    while time.time() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return out
        except Exception:
            break
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
        out["killed"] = True
    except ProcessLookupError:
        pass
    except Exception as e:
        out["error"] = f"sigkill: {e}"
    return out


def run_supervised(cmd, cwd=None, env=None, timeout=None, idle_timeout=None,
                   task_class=None, shell=False):
    """Run a lane under wall-clock AND heartbeat supervision.

    Returns a dict shaped like subprocess.run plus supervision fields:
        returncode  int  (124 on wall-clock timeout, 125 on idle kill)
        stdout/stderr    captured text
        timed_out / idle_killed  bool
        duration_s  float
        reap        dict from kill_process_group (proof the group was signalled)

    Output goes to temp FILES rather than pipes on purpose. Reading pipes
    requires either a reader thread or communicate(), and communicate() blocks
    uninterruptibly -- which is how you end up unable to enforce your own
    timeout. Files let the supervisor poll size as the heartbeat signal, so
    "is it alive" is answered by "did it write anything", which is what the
    directive asks for.
    """
    wall = timeout if timeout else timeout_for(task_class)
    idle = DEFAULT_IDLE_TIMEOUT_S if idle_timeout is None else idle_timeout
    result = {"returncode": 1, "stdout": "", "stderr": "", "timed_out": False,
              "idle_killed": False, "duration_s": 0.0, "reap": {}, "pid": None}
    if not ENABLED:
        # Escape hatch: fall back to plain subprocess (old behaviour) so the
        # guard can be switched off without editing call sites.
        try:
            p = subprocess.run(cmd, cwd=cwd, env=env, shell=shell,
                               capture_output=True, text=True, timeout=wall)
            return {**result, "returncode": p.returncode, "stdout": p.stdout or "",
                    "stderr": p.stderr or ""}
        except Exception as e:
            return {**result, "stderr": str(e)}

    t0 = time.time()
    out_f = err_f = proc = None
    try:
        out_f = tempfile.NamedTemporaryFile(mode="w+", suffix=".lane.out", delete=False)
        err_f = tempfile.NamedTemporaryFile(mode="w+", suffix=".lane.err", delete=False)
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, shell=shell,
            stdout=out_f, stderr=err_f, stdin=subprocess.DEVNULL,
            start_new_session=True,   # <- the fix: own process group
        )
        result["pid"] = proc.pid
        last_size, last_change = -1, time.time()
        while True:
            if proc.poll() is not None:
                break
            now = time.time()
            if now - t0 >= wall:
                result["timed_out"] = True
                result["reap"] = kill_process_group(proc.pid)
                result["returncode"] = 124
                break
            if idle and idle > 0:
                try:
                    size = os.path.getsize(out_f.name) + os.path.getsize(err_f.name)
                except OSError:
                    size = last_size
                if size != last_size:
                    last_size, last_change = size, now
                elif now - last_change >= idle:
                    result["idle_killed"] = True
                    result["reap"] = kill_process_group(proc.pid)
                    result["returncode"] = 125
                    break
            time.sleep(POLL_S)
        try:
            proc.wait(timeout=max(KILL_GRACE_S, 2))
        except Exception:
            pass
        if not result["timed_out"] and not result["idle_killed"]:
            result["returncode"] = proc.returncode if proc.returncode is not None else 1
    except Exception as e:
        result["stderr"] = f"{NAME}: {e}"
        if proc is not None:
            result["reap"] = kill_process_group(proc.pid)
    finally:
        for handle, key in ((out_f, "stdout"), (err_f, "stderr")):
            if handle is None:
                continue
            try:
                handle.flush()
                handle.close()
                with open(handle.name, errors="replace") as fh:
                    text = fh.read()
                result[key] = (result[key] + text) if result[key] else text
            except Exception:
                pass
            try:
                os.unlink(handle.name)
            except OSError:
                pass
        result["duration_s"] = round(time.time() - t0, 3)
    if result["timed_out"]:
        result["stderr"] += f"\n{NAME}: wall-clock timeout after {wall}s (process group reaped)"
    if result["idle_killed"]:
        result["stderr"] += f"\n{NAME}: no heartbeat for {idle}s (process group reaped)"
    return result


if __name__ == "__main__":
    import json
    argv = sys.argv[1:]
    if not argv:
        print(json.dumps({"default_timeout_s": DEFAULT_LANE_TIMEOUT_S,
                          "class_timeouts": CLASS_TIMEOUTS,
                          "idle_timeout_s": DEFAULT_IDLE_TIMEOUT_S}, indent=2))
    else:
        print(json.dumps(run_supervised(argv), indent=2, default=str))
