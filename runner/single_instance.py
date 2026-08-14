#!/usr/bin/env python3
"""
single_instance.py - one live copy per interval-scheduled script.

ROOT CAUSE (operator incident 2026-08-02): legal_docket.py leaked 14 concurrent
copies, some 8-10h old, on a 30-MINUTE interval. Nothing checked whether the
previous tick had finished, so every tick stacked another process on top of the
last. Together with the zombie coder lanes this starved the fleet of RAM until
the runner's mem-gate closed and claiming stopped fleet-wide.

An interval scheduler makes an implicit promise -- "run this every N minutes" --
that is only safe if a tick is guaranteed to be SHORTER than N. Nothing enforces
that, so the guarantee has to live in the script: a tick that finds the previous
tick still running logs and skips.

Uses fcntl.flock, matching repo_lock.py / install_lock.py. flock is the right
primitive because the kernel releases it when the holder dies, so a killed or
crashed daemon cannot leave a lock that blocks its own restart forever -- the
classic failure of PID-file locking.

Two layers, because the lock alone only stops STACKING and not a single run that
hangs forever:

  hold(name)          skip this tick if another is live
  enforce_max_runtime a daemon that exceeds interval*1.5 kills ITSELF

Fail-soft: if the locking infrastructure is unavailable (read-only disk, no
/tmp), run UNLOCKED rather than skip. A missed lock costs one duplicate tick; a
lock bug that silently disables a daemon costs the fleet the whole job.
"""
import contextlib
import fcntl
import os
import signal
import sys
import threading
import time

NAME = "single-instance"

LOCK_DIR = os.environ.get(
    "ORCH_SINGLE_INSTANCE_LOCK_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".runtime", "locks"),
)

# interval x this = the point at which a daemon is presumed hung and self-kills.
MAX_RUNTIME_FACTOR = float(os.environ.get("ORCH_DAEMON_MAX_RUNTIME_FACTOR", "1.5"))

ENABLED = os.environ.get("ORCH_SINGLE_INSTANCE_ENABLED", "true").lower() in (
    "1", "true", "yes", "on")


def _sanitize(name):
    keep = "-_."
    cleaned = "".join(c if (c.isalnum() or c in keep) else "-" for c in str(name or "unnamed"))
    return cleaned[:120] or "unnamed"


def lock_path(name):
    return os.path.join(LOCK_DIR, f"daemon-{_sanitize(name)}.lock")


@contextlib.contextmanager
def hold(name, stale_after=None):
    """Yield True if this process owns `name`, False if another tick is live.

    Callers MUST check the yielded value and skip their work on False:

        with single_instance.hold("legal_docket") as owned:
            if not owned:
                return  # previous tick still running
            ...

    The lock is non-blocking by design. Waiting would just rebuild the pile-up
    with the processes parked in flock() instead of doing work.
    """
    if not ENABLED:
        yield True
        return
    f = None
    owned = False
    try:
        os.makedirs(LOCK_DIR, exist_ok=True)
        f = open(lock_path(name), "a+")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            owned = True
        except (BlockingIOError, OSError):
            owned = False
        if owned:
            try:
                f.seek(0)
                f.truncate()
                f.write(f"{os.getpid()} {int(time.time())} {name}\n")
                f.flush()
            except Exception:
                pass
        yield owned
    except Exception:
        # Infrastructure failure -- run rather than silently disable the job.
        yield True
    finally:
        if f is not None:
            try:
                if owned:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                f.close()
            except Exception:
                pass


def holder_pid(name):
    """PID recorded in the lock file, or None. Telemetry only -- the flock, not
    this number, is the authority on who holds the lock."""
    try:
        with open(lock_path(name)) as fh:
            return int((fh.read().split() or ["0"])[0])
    except Exception:
        return None


def is_locked(name):
    """True if some other process currently holds `name`."""
    try:
        os.makedirs(LOCK_DIR, exist_ok=True)
        with open(lock_path(name), "a+") as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                return False
            except (BlockingIOError, OSError):
                return True
    except Exception:
        return False


def max_runtime_for(interval_s, factor=None):
    """Self-kill deadline for a daemon on an `interval_s` schedule."""
    try:
        interval = float(interval_s)
    except (TypeError, ValueError):
        return 0.0
    if interval <= 0:
        return 0.0
    return interval * (MAX_RUNTIME_FACTOR if factor is None else float(factor))


def enforce_max_runtime(interval_s, factor=None, name=None, _exit=None):
    """Arm a watchdog that kills THIS process if it outlives interval*factor.

    The lock stops ticks from stacking; it does not help if tick #1 hangs
    forever, because then the job simply never runs again -- the lock turns a
    hang into a silent permanent outage. This bounds that: the hung tick dies
    and the next scheduled tick takes the lock cleanly.

    Daemon thread, so it never keeps a healthy process alive. Returns the timer
    (call .cancel() on clean early exit) or None if not armed.
    """
    deadline = max_runtime_for(interval_s, factor)
    if deadline <= 0:
        return None
    label = name or os.path.basename(sys.argv[0] or "daemon")

    def _fire():
        try:
            sys.stderr.write(
                f"{NAME}: {label} exceeded max runtime {deadline:.0f}s -- self-terminating\n")
            sys.stderr.flush()
        except Exception:
            pass
        if _exit is not None:
            _exit()
            return
        try:
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(5)
            os.kill(os.getpid(), signal.SIGKILL)
        except Exception:
            os._exit(124)

    t = threading.Timer(deadline, _fire)
    t.daemon = True
    t.start()
    return t


def guard(name, interval_s=None, factor=None):
    """One-call setup for an interval daemon.

    Returns (owned, timer). On owned=False the caller must exit immediately.

        owned, timer = single_instance.guard("legal_docket", interval_s=1800)
        if not owned:
            sys.exit(0)

    NOTE: the lock is released when the returned context is garbage collected or
    the process exits -- flock is held for the lifetime of the open file, and we
    intentionally keep that file open for the whole run.
    """
    cm = hold(name)
    owned = cm.__enter__()
    if not owned:
        try:
            cm.__exit__(None, None, None)
        except Exception:
            pass
        return False, None
    guard._held.append(cm)  # keep the fd (and thus the flock) alive
    timer = enforce_max_runtime(interval_s, factor, name=name) if interval_s else None
    return True, timer


guard._held = []


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    print(f"{target}: locked={is_locked(target)} holder={holder_pid(target)} "
          f"path={lock_path(target)}")
