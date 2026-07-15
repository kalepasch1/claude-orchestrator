#!/usr/bin/env python3
"""Per-repo file lock so concurrent integration attempts never race on shared git refs.

ROOT CAUSE (2026-07-08 merge-stall, 0 merges for 32+ hours): merge_train.train_run() is
invoked from many places concurrently -- the "train-60" scheduled interval job AND, inline,
after every successful integrate().  Without serialisation each instance does
fetch/rebase/push in parallel, causing non-fast-forward failures that look like
"remote rejected".

FIX: one advisory flock per repo path, hashed to a predictable filename so every
process on this Mac contends on the same file.
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

# MERGE-PRIORITY YIELD (2026-07-15 merge-starvation fix)

def _lock_path(repo):
    key = hashlib.sha1(str(repo or "unknown-repo").encode()).hexdigest()[:16]
    return os.path.join(LOCK_DIR, f"repo-{key}.lock")

def _priority_path(repo):
    key = hashlib.sha1(str(repo or "unknown-repo").encode()).hexdigest()[:16]
    return os.path.join(LOCK_DIR, f"repo-{key}.merge-priority")

def request_priority(repo):
    """Signal that merge_train wants the lock — integrate() threads will yield."""
    try:
        os.makedirs(LOCK_DIR, exist_ok=True)
        with open(_priority_path(repo), "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass

def release_priority(repo):
    """Clear the priority signal."""
    try:
        os.remove(_priority_path(repo))
    except Exception:
        pass

def _merge_waiting(repo):
    """Check if merge_train has requested priority within the last 10 minutes."""
    try:
        p = _priority_path(repo)
        if not os.path.exists(p):
            return False
        with open(p) as f:
            ts = float(f.read().strip())
        if time.time() - ts > 600:
            try:
                os.remove(p)
            except Exception:
                pass
            return False
        return True
    except Exception:
        return False

@contextlib.contextmanager
def hold(repo, timeout=None, priority=False):
    """Acquire the per-repo flock.

    priority=True: used by merge_train to signal integrate() threads to yield.
    Non-priority callers sleep 2s when merge_train is waiting, creating a window.
    """
    if priority:
        request_priority(repo)
    f = None
    try:
        os.makedirs(LOCK_DIR, exist_ok=True)
        f = open(_lock_path(repo), "a+")
    except Exception:
        if priority:
            release_priority(repo)
        yield True
        return
    acquired = False
    # Cooperative yield: if merge_train is waiting, non-priority callers pause
    if not priority and _merge_waiting(repo):
        time.sleep(2)
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
                if priority:
                    release_priority(repo)
                yield False
                return
        else:
            fcntl.flock(f, fcntl.LOCK_EX)
            acquired = True
        yield True
    finally:
        if priority:
            release_priority(repo)
        if acquired:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            except Exception:
                pass
        try:
            f.close()
        except Exception:
            pass
