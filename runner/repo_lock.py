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
claimed), instead of racing. Lock infrastructure failures fail closed: skipping one mutation is
recoverable; allowing concurrent writers into shared refs can destroy or strand fleet work.
"""
import contextlib
import fcntl
import hashlib
import os
import time

LOCK_DIR = os.environ.get(
    "ORCH_REPO_LOCK_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".runtime", "locks"),
)


def _lock_path(repo):
    key = hashlib.sha1(str(repo or "unknown-repo").encode()).hexdigest()[:16]
    return os.path.join(LOCK_DIR, f"repo-{key}.lock")


@contextlib.contextmanager
def hold(repo, timeout=None):
    """Exclusive lock scoped to `repo`. Yields True if the lock was acquired, False if the
    lock could not be obtained within `timeout` -- callers should skip their git-mutating
    work on False rather than proceed unprotected. If the locking infrastructure itself is
    unavailable (no repo, disk full, etc.), fail closed so callers never mutate shared refs
    without serialization."""
    f = None
    try:
        os.makedirs(LOCK_DIR, exist_ok=True)
        f = open(_lock_path(repo), "a+")
    except Exception:
        yield False
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
