#!/usr/bin/env python3
"""
lane_guard.py — lane + daemon immune system (operator directive 2026-08-02, P0).

Root cause of the 2026-08-02 incident: `claude_cli.run()` shelled out via
`subprocess.run(..., timeout=timeout)` with `timeout=None` on the default path, so a
headless coder session that wedged was never killed. 64 of 66 lanes ended up zombies
>1h old, pinning all RAM and slots; the mem-gate then correctly refused new claims
(claimable=803, claiming ~0). Separately `legal_docket.py` leaked 14 concurrent copies
because interval-scheduled scripts had no single-instance lock.

This module is the durable, in-process fix. `runner/tools/lane_medic.sh` stays as an
out-of-band backstop launched by keepalive, but it is no longer the mechanism.

Three guarantees:

  1. WALL-CLOCK + HEARTBEAT. Every agentic-coder invocation runs through `run_guarded()`,
     which puts the child in its OWN process group (`start_new_session=True`) and kills
     the whole group on expiry. `subprocess.run`'s own timeout only kills the direct
     child — the `claude` binary's descendants survived it, which is why reaping never
     worked. A lane that produces no stdout/stderr for `heartbeat_grace` seconds is
     reaped early, before it burns the full wall-clock budget.

  2. SINGLE INSTANCE. `single_instance()` is an flock-based context manager for every
     interval-scheduled script. A tick that finds the lock held logs and skips instead
     of stacking another copy. Each holder also arms a max-runtime self-kill.

  3. TELEMETRY + ALERTS. `telemetry()` feeds the SLO dashboard (live lane count, age
     histogram, reaps/hour, mem-gate state and its RAM reading). `check_and_alert()`
     pages the operator when lanes exceed throttle+5 or the mem-gate has been closed
     for more than 15 minutes.

CLI:
    python3 runner/lane_guard.py telemetry     # JSON snapshot for the dashboard
    python3 runner/lane_guard.py sweep         # reap + alert (scheduler calls this)
"""
import os
import sys
import json
import time
import errno
import signal
import fcntl
import shlex
import atexit
import threading
import subprocess
import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


def _env_int(name, default):
    try:
        return int(float(os.environ.get(name, "") or default))
    except Exception:
        return int(default)


# ── Per-task-class wall-clock limits ─────────────────────────────────────────
# Default 45m per the directive. Classes that legitimately run long get more; cheap
# classes get less so a wedged lane frees its slot sooner. Override any entry with
# ORCH_LANE_TIMEOUT_<CLASS> (minutes), or the default with ORCH_LANE_TIMEOUT_MIN.
DEFAULT_LANE_TIMEOUT_MIN = 45

CLASS_TIMEOUT_MIN = {
    "canary": 15,
    "toolchain-repair": 20,
    "qafix": 30,
    "bugfix": 30,
    "recovery": 45,
    "build": 45,
    "feature": 60,
    "legal": 60,
    "security": 60,
}

# A lane silent this long is presumed wedged and is reaped before its wall-clock budget.
DEFAULT_HEARTBEAT_GRACE_MIN = 12

# Lane-count alert threshold is throttle + this many.
LANE_ALERT_SLACK = 5

# Mem-gate closed longer than this pages the operator.
MEM_GATE_ALERT_MIN = 15

LOG_DIR = os.path.join(_ROOT, ".runtime", "logs")
LOCK_DIR = os.environ.get("ORCH_LOCK_DIR") or os.path.join(_ROOT, ".runtime", "locks")
REAP_LOG = os.path.join(LOG_DIR, "lane-guard-reaps.jsonl")


def class_timeout(task_class=None, default_min=None):
    """Wall-clock seconds allowed for one agentic-coder invocation of this task class."""
    base = _env_int("ORCH_LANE_TIMEOUT_MIN", default_min or DEFAULT_LANE_TIMEOUT_MIN)
    key = (task_class or "").strip().lower()
    minutes = CLASS_TIMEOUT_MIN.get(key, base)
    override = os.environ.get("ORCH_LANE_TIMEOUT_" + key.upper().replace("-", "_"))
    if override:
        try:
            minutes = int(float(override))
        except Exception:
            pass
    return max(60, int(minutes) * 60)


def heartbeat_grace(task_class=None):
    """Seconds of total output silence after which a lane is presumed wedged."""
    grace = _env_int("ORCH_LANE_HEARTBEAT_MIN", DEFAULT_HEARTBEAT_GRACE_MIN) * 60
    # Never reap on silence before a quarter of the wall-clock budget has elapsed.
    return max(120, min(grace, class_timeout(task_class)))


# ── Reap ledger (feeds reaps/hour on the dashboard) ──────────────────────────
def _log_reap(kind, **fields):
    rec = {"ts": time.time(), "iso": datetime.datetime.utcnow().isoformat() + "Z", "kind": kind}
    rec.update(fields)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(REAP_LOG, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass
    try:
        import resource_governor
        resource_governor.emit("lane_reap", **{k: v for k, v in fields.items() if v is not None})
    except Exception:
        pass
    return rec


def recent_reaps(window_s=3600):
    """Reaps recorded in the last `window_s` seconds — the dashboard's reaps/hour."""
    cutoff = time.time() - window_s
    out = []
    try:
        with open(REAP_LOG) as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if float(rec.get("ts", 0)) >= cutoff:
                    out.append(rec)
    except IOError:
        pass
    return out


# ── Process-group kill ───────────────────────────────────────────────────────
def kill_process_tree(pid, grace_s=10):
    """SIGTERM then SIGKILL an entire process group.

    The whole point of the module. `subprocess.run(timeout=)` calls `proc.kill()`, which
    signals only the direct child; the `claude` CLI's descendants kept running and kept
    holding RAM. Children are started with `start_new_session=True`, so the child pid is
    its own process-group leader and one killpg takes the tree down.
    """
    try:
        pgid = os.getpgid(pid)
    except OSError:
        return False
    if pgid == os.getpgid(0):
        # Refuse to signal our own group — that would kill the runner itself.
        return False
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                return True          # already gone
        deadline = time.time() + (grace_s if sig == signal.SIGTERM else 3)
        while time.time() < deadline:
            try:
                os.killpg(pgid, 0)
            except OSError:
                return True          # group is gone
            time.sleep(0.25)
    return False


class _Pump(threading.Thread):
    """Drains one pipe into a buffer and stamps every read as lane activity."""

    def __init__(self, stream, state, key):
        threading.Thread.__init__(self)
        self.daemon = True
        self._stream, self._state, self._key = stream, state, key
        self.chunks = []

    def run(self):
        try:
            for chunk in iter(lambda: self._stream.readline(), ""):
                if not chunk:
                    break
                self.chunks.append(chunk)
                self._state["last_activity"] = time.time()
        except Exception:
            pass
        finally:
            try:
                self._stream.close()
            except Exception:
                pass

    def text(self):
        return "".join(self.chunks)


def run_guarded(cmd, cwd=None, env=None, timeout=None, task_class=None,
                grace_s=None, task_id=None, coder=None, popen=None):
    """Run `cmd` under a hard wall-clock limit AND a heartbeat (output-silence) limit.

    Returns a `subprocess.CompletedProcess`. Raises `subprocess.TimeoutExpired` when the
    lane is reaped, so existing callers that already handle TimeoutExpired (returncode
    124 in agentic_coders.run) keep working unchanged.

    `popen` is injectable for tests.
    """
    limit = int(timeout or class_timeout(task_class))
    silence = int(grace_s if grace_s is not None else heartbeat_grace(task_class))
    spawn = popen or subprocess.Popen
    argv = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)

    proc = spawn(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                 text=True, start_new_session=True)
    started = time.time()
    state = {"last_activity": started}
    pumps = [_Pump(proc.stdout, state, "out"), _Pump(proc.stderr, state, "err")]
    for p in pumps:
        p.start()

    reaped_for = None
    while True:
        if proc.poll() is not None:
            break
        now = time.time()
        if now - started > limit:
            reaped_for = "wall_clock"
        elif now - state["last_activity"] > silence:
            reaped_for = "no_heartbeat"
        if reaped_for:
            kill_process_tree(proc.pid, grace_s=10)
            break
        time.sleep(0.5)

    for p in pumps:
        p.join(timeout=5)
    try:
        proc.wait(timeout=5)
    except Exception:
        pass
    out, err = pumps[0].text(), pumps[1].text()
    elapsed = round(time.time() - started, 1)

    if reaped_for:
        _log_reap("lane_reaped", reason=reaped_for, pid=proc.pid, elapsed_s=elapsed,
                  limit_s=limit, silence_s=silence, task_id=task_id,
                  task_class=task_class, coder=coder)
        raise subprocess.TimeoutExpired(cmd=argv, timeout=limit, output=out, stderr=err)

    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def release_lane_to_retry(task_id, reason, note=None):
    """Hand a reaped task back to the queue as RETRY so the lane is genuinely freed.

    Best-effort: a DB outage must never stop the reap itself, which is the part that
    protects the machine.
    """
    if not task_id:
        return False
    text = note or "lane_guard: reaped ({0}) — lane freed, requeued for retry".format(reason)
    try:
        import db
        db.update("tasks", {"id": "eq.{0}".format(task_id)}, {"state": "RETRY", "note": text})
        return True
    except Exception as exc:
        _log_reap("retry_mark_failed", task_id=task_id, reason=reason, error=str(exc))
        return False


# ── Single-instance locks for interval-scheduled scripts ─────────────────────
class AlreadyRunning(Exception):
    """Raised when another copy of an interval script still holds the lock."""


def lock_path(name):
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(name))
    return os.path.join(LOCK_DIR, safe + ".lock")


def _arm_max_runtime(name, max_runtime_s):
    """Hard ceiling inside the daemon itself (interval x1.5 by default).

    legal_docket ran on a 30-minute interval and accumulated copies 8-10h old. Even with
    the lock, a single wedged copy would hold it forever, so each holder also arms a
    watchdog that takes its own process group down.
    """
    if not max_runtime_s:
        return None

    def _blow_up():
        _log_reap("daemon_max_runtime", name=name, pid=os.getpid(), limit_s=int(max_runtime_s))
        try:
            os.killpg(os.getpgid(0), signal.SIGKILL)
        except Exception:
            os._exit(124)

    timer = threading.Timer(float(max_runtime_s), _blow_up)
    timer.daemon = True
    timer.start()
    return timer


class single_instance(object):
    """Context manager: exclusive flock for one named interval script.

    Usage in a daemon (interval 1800s):

        import lane_guard
        try:
            with lane_guard.single_instance("legal_docket", interval_s=1800):
                main()
        except lane_guard.AlreadyRunning:
            print("[legal_docket] previous tick still running — skipping")
            sys.exit(0)

    Or non-raising:  `with lane_guard.single_instance("x", block=False) as held:`
    where `held` is False when another copy holds the lock.
    """

    def __init__(self, name, interval_s=None, max_runtime_s=None, raise_on_busy=True):
        self.name = name
        self.raise_on_busy = raise_on_busy
        if max_runtime_s is None and interval_s:
            max_runtime_s = float(interval_s) * 1.5
        self.max_runtime_s = max_runtime_s
        self.path = lock_path(name)
        self._fh = None
        self._timer = None
        self.held = False

    def __enter__(self):
        os.makedirs(LOCK_DIR, exist_ok=True)
        self._fh = open(self.path, "a+")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            holder = ""
            try:
                self._fh.seek(0)
                holder = self._fh.read().strip()
            except Exception:
                pass
            self._fh.close()
            self._fh = None
            _log_reap("daemon_tick_skipped", name=self.name, holder=holder)
            if self.raise_on_busy:
                raise AlreadyRunning("{0} already running ({1})".format(self.name, holder))
            return False
        self.held = True
        try:
            self._fh.seek(0)
            self._fh.truncate()
            self._fh.write(json.dumps({"pid": os.getpid(), "started": time.time(),
                                       "host": os.uname().nodename}))
            self._fh.flush()
        except Exception:
            pass
        self._timer = _arm_max_runtime(self.name, self.max_runtime_s)
        atexit.register(self._release)
        return True

    def __exit__(self, *exc):
        self._release()
        return False

    def _release(self):
        if self._timer:
            try:
                self._timer.cancel()
            except Exception:
                pass
            self._timer = None
        if self._fh:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
        self.held = False


def lock_held(name):
    """Probe (without taking) whether another process holds this script's lock.

    Used by the scheduler as a cheap pre-launch skip. It is advisory — the authoritative
    guarantee is the holder's own `single_instance` block, because a daemon started by
    launchd or by hand never passes through the scheduler at all.
    """
    path = lock_path(name)
    if not os.path.exists(path):
        return False
    try:
        fh = open(path, "a+")
    except IOError:
        return False
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        return False
    except IOError:
        return True
    finally:
        try:
            fh.close()
        except Exception:
            pass


def guard_or_exit(name, interval_s=None, max_runtime_s=None):
    """One-liner for a script's `__main__`. Returns the held lock, or exits 0 if busy."""
    lock = single_instance(name, interval_s=interval_s, max_runtime_s=max_runtime_s,
                           raise_on_busy=False)
    if not lock.__enter__():
        print("[{0}] previous tick still running — skipping this launch".format(name), flush=True)
        sys.exit(0)
    return lock


# ── Lane telemetry (lane_medic.sh logic, adopted into the scheduler) ─────────
LANE_PATTERN = os.environ.get("ORCH_LANE_PATTERN", "claude --output-format")
DAEMON_PATTERNS = ("legal_docket.py", "expert_corps.py", "benchmark_redlines.py",
                   "foulkon_sync.py")


def etime_minutes(etime):
    """Parse `ps -o etime` ([[DD-]HH:]MM:SS) into whole minutes.

    lane_medic.sh collapsed anything with a day component to a sentinel 99999; the
    dashboard needs a real age for its histogram, so parse it properly.
    """
    text = str(etime).strip()
    days = 0
    if "-" in text:
        d, _, text = text.partition("-")
        try:
            days = int(d)
        except ValueError:
            days = 0
    parts = text.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return 0
    if len(nums) == 3:
        h, m, s = nums
    elif len(nums) == 2:
        h, (m, s) = 0, nums
    else:
        h, m, s = 0, 0, nums[0]
    # Floor, never round up: this number feeds kill thresholds, and rounding a 99m30s lane
    # up to 100 would reap it half a minute early. Under-reporting age is the safe error.
    return days * 1440 + h * 60 + m


def _ps_lines():
    try:
        out = subprocess.run(["ps", "-axo", "pid=,etime=,command="],
                             capture_output=True, text=True, timeout=20)
    except Exception:
        return []
    rows = []
    for line in (out.stdout or "").splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid, etime, command = parts
        try:
            rows.append({"pid": int(pid), "age_min": etime_minutes(etime), "command": command})
        except ValueError:
            continue
    return rows


def _self_pids():
    return {os.getpid(), os.getppid()}


def live_lanes(rows=None):
    rows = _ps_lines() if rows is None else rows
    mine = _self_pids()
    return [r for r in rows
            if LANE_PATTERN in r["command"] and r["pid"] not in mine and "lane_guard" not in r["command"]]


def age_histogram(lanes):
    buckets = {"lt_15m": 0, "15_45m": 0, "45_90m": 0, "gt_90m": 0}
    for lane in lanes:
        age = lane["age_min"]
        if age < 15:
            buckets["lt_15m"] += 1
        elif age < 45:
            buckets["15_45m"] += 1
        elif age < 90:
            buckets["45_90m"] += 1
        else:
            buckets["gt_90m"] += 1
    return buckets


def mem_gate_state():
    """Open/closed state of the claim gate plus the RAM reading behind it."""
    state = {"open": None, "reason": "unavailable", "free_ram_gb": None, "floor_gb": None}
    try:
        import resource_governor
        ok, reason = resource_governor.can_claim()
        state["open"], state["reason"] = bool(ok), reason
        state["free_ram_gb"] = resource_governor.ram_free_gb()
        state["floor_gb"] = resource_governor.effective_floor_gb()
    except Exception as exc:
        state["reason"] = "resource_governor unavailable: {0}".format(exc)
    return state


_GATE_CLOSED_SINCE = os.path.join(LOG_DIR, "lane-guard-gate-closed-since")


def _track_gate_closed(is_open):
    """Persist when the mem-gate first closed so the 15-minute alert survives restarts."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        if is_open:
            if os.path.exists(_GATE_CLOSED_SINCE):
                os.remove(_GATE_CLOSED_SINCE)
            return 0.0
        if not os.path.exists(_GATE_CLOSED_SINCE):
            with open(_GATE_CLOSED_SINCE, "w") as fh:
                fh.write(str(time.time()))
            return 0.0
        with open(_GATE_CLOSED_SINCE) as fh:
            return (time.time() - float(fh.read().strip())) / 60.0
    except Exception:
        return 0.0


def throttle_limit():
    for name in ("ORCH_MAX_PARALLEL", "MAX_PARALLEL", "ORCH_THROTTLE"):
        val = os.environ.get(name)
        if val:
            try:
                return int(float(val))
            except Exception:
                continue
    return _env_int("ORCH_LANE_THROTTLE_DEFAULT", 8)


def telemetry():
    """Snapshot for the SLO dashboard."""
    rows = _ps_lines()
    lanes = live_lanes(rows)
    gate = mem_gate_state()
    closed_min = _track_gate_closed(gate.get("open") is not False)
    reaps = recent_reaps(3600)
    daemons = {}
    for pattern in DAEMON_PATTERNS:
        hits = [r for r in rows if pattern in r["command"]]
        if hits:
            daemons[pattern] = {"count": len(hits),
                                "oldest_min": max(h["age_min"] for h in hits)}
    return {
        "ts": time.time(),
        "lane_count": len(lanes),
        "lane_throttle": throttle_limit(),
        "lane_age_histogram": age_histogram(lanes),
        "oldest_lane_min": max([l["age_min"] for l in lanes] or [0]),
        "reaps_last_hour": len(reaps),
        "reaps_by_reason": _tally(reaps),
        "mem_gate_open": gate.get("open"),
        "mem_gate_reason": gate.get("reason"),
        "mem_gate_closed_min": round(closed_min, 1),
        "free_ram_gb": gate.get("free_ram_gb"),
        "ram_floor_gb": gate.get("floor_gb"),
        "interval_daemons": daemons,
    }


def _tally(reaps):
    out = {}
    for rec in reaps:
        key = rec.get("reason") or rec.get("kind") or "unknown"
        out[key] = out.get(key, 0) + 1
    return out


def reap_zombie_lanes(max_age_min=None, dry_run=False):
    """Backstop sweep for lanes that predate the in-process guard (or escaped it)."""
    ceiling = max_age_min or _env_int("ORCH_LANE_MAX_AGE_MIN", 100)
    reaped = []
    for lane in live_lanes():
        if lane["age_min"] < ceiling:
            continue
        if dry_run or kill_process_tree(lane["pid"], grace_s=5):
            reaped.append(lane)
            if not dry_run:
                _log_reap("lane_reaped", reason="stale_sweep", pid=lane["pid"],
                          elapsed_s=lane["age_min"] * 60, limit_s=ceiling * 60)
    return reaped


def reap_stuck_daemons(dry_run=False):
    """Kill interval daemons past interval x1.5 — the legal_docket leak class."""
    ceiling = _env_int("ORCH_DAEMON_MAX_AGE_MIN", 45)
    rows = _ps_lines()
    reaped = []
    for pattern in DAEMON_PATTERNS:
        hits = sorted([r for r in rows if pattern in r["command"]],
                      key=lambda r: r["age_min"])
        for hit in hits[1:] + [h for h in hits[:1] if h["age_min"] >= ceiling]:
            if dry_run or kill_process_tree(hit["pid"], grace_s=5):
                reaped.append(hit)
                if not dry_run:
                    _log_reap("daemon_reaped", reason="stuck_or_duplicate", pid=hit["pid"],
                              name=pattern, elapsed_s=hit["age_min"] * 60)
    return reaped


def check_and_alert(snapshot=None, notifier=None):
    """Page the operator when lanes exceed throttle+5 or the mem-gate is stuck closed."""
    snap = snapshot or telemetry()
    alerts = []
    ceiling = snap["lane_throttle"] + LANE_ALERT_SLACK
    if snap["lane_count"] > ceiling:
        alerts.append("lane leak: {0} live lanes > throttle {1} + {2} (oldest {3}m)".format(
            snap["lane_count"], snap["lane_throttle"], LANE_ALERT_SLACK, snap["oldest_lane_min"]))
    if snap["mem_gate_open"] is False and snap["mem_gate_closed_min"] >= MEM_GATE_ALERT_MIN:
        alerts.append("mem-gate closed {0}m — {1} (free RAM {2}GB, floor {3}GB)".format(
            int(snap["mem_gate_closed_min"]), snap["mem_gate_reason"],
            snap["free_ram_gb"], snap["ram_floor_gb"]))
    for pattern, info in (snap.get("interval_daemons") or {}).items():
        if info["count"] > 1:
            alerts.append("{0}: {1} concurrent copies (oldest {2}m) — lock leak".format(
                pattern, info["count"], info["oldest_min"]))
    if alerts:
        send = notifier
        if send is None:
            try:
                import notify
                send = notify.send
            except Exception:
                send = lambda m: print("[lane_guard] " + m, flush=True)
        for msg in alerts:
            send("[fleet-immune] " + msg)
    return alerts


def sweep():
    """One scheduler tick: backstop reaps, then telemetry, then alerts."""
    lanes = reap_zombie_lanes()
    daemons = reap_stuck_daemons()
    snap = telemetry()
    alerts = check_and_alert(snap)
    snap["swept_lanes"] = len(lanes)
    snap["swept_daemons"] = len(daemons)
    snap["alerts"] = alerts
    return snap


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    # Default is `sweep`: the scheduler launches this module with no arguments, and the
    # scheduled action is reap-then-alert. `telemetry` is the read-only variant.
    cmd = (argv[0] if argv else "sweep").lower()
    if cmd == "sweep":
        print(json.dumps(sweep(), indent=2, default=str))
    elif cmd in ("telemetry", "status"):
        print(json.dumps(telemetry(), indent=2, default=str))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
