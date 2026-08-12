#!/usr/bin/env python3
"""Per-repo file lock so concurrent integration attempts never race on shared git refs.

ROOT CAUSE (2026-07-08 merge-stall, 0 merges for 32+ hours): merge_train.train_run() is
invoked from many places concurrently -- the "train-60" scheduled interval job AND, inline,
from every worker thread's runner.py integrate() call the instant a task finishes (runner.py
spawns one thread per claimed task, and a project can have many tasks RUNNING at once). The
train's docstring promises "serialized per project", but that serialization only held WITHIN
a single train_run() call -- nothing stopped two SEPARATE, CONCURRENT train_run() calls from
processing the same project's repo at the same time. Each one rebases agent/<slug> onto the
shared local base branch, force-moves branch pointers (`git branch -f`), and fast-forwards
base -- all against the SAME on-disk repo, with no mutual exclusion. Concurrent callers raced:
one thread's rebase-in-progress could be yanked out from under it by another thread resetting
the same branch ref, producing spurious rebase conflicts that were not real content conflicts.
Those conflicts exhausted MERGE_CONFLICT_REDO_CAP, tasks were marked CONFLICT, quarantine spun
up replacement "rework-*" tasks, and the rework tasks hit the exact same race on their next
pass -- an infinite loop that grew QUARANTINED/QUEUED counts while MERGED stayed flat.

Fix: every git-mutating integration step for a given repo acquires this lock first. Concurrent
callers now queue up and run one at a time per repo (matching what the train's docstring always
claimed), instead of racing. Fail-soft: if the lock file itself can't be opened/locked, proceed
unlocked rather than wedge the runner -- a missed lock is a lot cheaper than a stuck fleet.
"""
import contextlib
import fcntl
import hashlib
import json
import os
import socket
import time

LOCK_DIR = os.environ.get(
    "ORCH_REPO_LOCK_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".runtime", "locks"),
)


def _lock_path(repo):
    key = hashlib.sha1(str(repo or "unknown-repo").encode()).hexdigest()[:16]
    return os.path.join(LOCK_DIR, f"repo-{key}.lock")


def _write_holder(handle, repo, purpose):
    """Stamp who holds the lock. Called only while the flock is held."""
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "purpose": purpose or "",
            "repo": str(repo or ""),
            "acquired_at": time.time(),
        }))
        handle.flush()
    except Exception:
        pass  # diagnostics only; never let bookkeeping break the lock


def describe_holder(repo):
    """Best-effort description of the last process to take this repo's lock.

    Waiters call this on timeout so the failure names a culprit. A bare
    "repository isolation lock unavailable" is undiagnosable: it cannot
    distinguish a long-running merge-train rebase (wait longer) from a wedged
    holder (intervene). Returns '' when nothing is known.
    """
    try:
        with open(_lock_path(repo), "r") as fh:
            info = json.loads(fh.read() or "{}")
    except Exception:
        return ""
    if not isinstance(info, dict) or not info.get("pid"):
        return ""
    held = ""
    try:
        held = " for {0:.0f}s".format(max(0.0, time.time() - float(info["acquired_at"])))
    except Exception:
        pass
    alive = ""
    try:
        os.kill(int(info["pid"]), 0)
        alive = "alive"
    except ProcessLookupError:
        alive = "DEAD (lock already released by the kernel)"
    except Exception:
        alive = "unknown"
    return "last holder pid={0} host={1} purpose={2}{3} ({4})".format(
        info.get("pid"), info.get("host") or "?",
        info.get("purpose") or "unspecified", held, alive)


@contextlib.contextmanager
def hold(repo, timeout=None, purpose=None):
    """Exclusive lock scoped to `repo`. Yields True if the lock was acquired, False if the
    lock could not be obtained within `timeout` -- callers should skip their git-mutating
    work on False rather than proceed unprotected. If the locking infrastructure itself is
    unavailable (no repo, disk full, etc.), fail-soft to unlocked so a lock bug never becomes
    a full fleet outage."""
    f = None
    try:
        os.makedirs(LOCK_DIR, exist_ok=True)
        f = open(_lock_path(repo), "a+")
    except Exception:
        yield True  # fail-soft: locking infra unavailable, proceed unlocked
        return
    acquired = False
    try:
        if timeout:
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except (BlockingIOError, OSError):
                    time.sleep(0.25)
            if not acquired:
                yield False
                return
        else:
            fcntl.flock(f, fcntl.LOCK_EX)
            acquired = True
        _write_holder(f, repo, purpose)
        yield True
    finally:
        if acquired:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            except Exception:
                pass
        try:
            f.close()
        except Exception:
            pass
