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
claimed), instead of racing.

FAILS CLOSED (changed 2026-08-24). hold() used to yield True when the lock directory or lock
file could not be opened -- "a missed lock is a lot cheaper than a stuck fleet". The incident
described above is what a missed lock costs: 32 hours of zero merges and a rework loop that
regenerated itself. It is not cheaper. And the fail-open case is never safe in the way it was
meant to be: if LOCK_DIR is uncreatable, EVERY process on the host hits the same wall, so
nobody is holding a lock and nobody is protected -- proceeding just means all of them mutate
the same refs at once, silently.

Yielding False instead is not an outage either, because every caller already treats False as
transient: runner.integrate() returns CONFLICT (redo-able), merge_train skips the cycle,
continuous_merger defers to the backlog sweep, worktree_isolation raises a retryable
WorktreeIsolationError, dirty_checkout_recovery publishes a "will retry" card. The failure is
logged at ERROR with the offending path so it is attributable rather than silent.
"""
import contextlib
import fcntl
import hashlib
import json
import logging
import os
import socket
import time

log = logging.getLogger(__name__)

_DEFAULT_LOCK_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".runtime", "locks")

LOCK_DIR = os.environ.get("ORCH_REPO_LOCK_DIR", _DEFAULT_LOCK_DIR)


def lock_dir():
    """Where the flocks live, resolved at CALL time.

    Prefer this over reading LOCK_DIR directly, for the reason build_slots.slot_dir()
    and _gate_load_ledger_path() already exist: 94 modules take their state directory
    from CLAUDE_ORCH_HOME so a test cannot write into the running fleet, and this one
    did not. It resolved once at IMPORT, before any fixture could redirect it.

    MEASURED 2026-09-04: 1,252 lock files in the live directory
    runner/.runtime/locks, the overwhelming majority stamped with holders like

        {"pid": 59070, "host": "Mac.lan",
         "repo": "/private/tmp/pytest-of-kpasch/pytest-9/test_noop_when_current_..."}

    -- every pytest run since this module was written, littering the directory the
    fleet serialises its real repositories through. Harmless in practice (an flock on
    a hashed path nothing else uses) but unbounded, and one hash collision away from
    a test contending with a live repo.

    Precedence is deliberate. An explicit ORCH_REPO_LOCK_DIR is an operator pointing
    the fleet somewhere on purpose and wins outright. A monkeypatched LOCK_DIR is a
    test being specific about this module and wins next -- several tests do exactly
    that, including the one that checks an unopenable directory yields a falsy lease.
    CLAUDE_ORCH_HOME then catches everything else, which is the whole point.
    """
    explicit = os.environ.get("ORCH_REPO_LOCK_DIR")
    if explicit:
        return explicit
    if LOCK_DIR != _DEFAULT_LOCK_DIR:
        return LOCK_DIR
    home = os.environ.get("CLAUDE_ORCH_HOME")
    if home:
        return os.path.join(home, "locks")
    return LOCK_DIR


def _canonical(repo):
    """One repo, one key -- whatever path spelling the caller happens to have.

    This hashed the RAW STRING, so two spellings of the same directory produced two
    different lock files and did not exclude each other at all. Verified on this
    machine, where ~/claude-orchestrator is a symlink to its real path:

        /Users/kpasch/claude-orchestrator                      -> repo-96d7193fa0854cac
        /Users/kpasch/Documents/beethoven/claude-orchestrator  -> repo-2b7b112e1dbf0ca3
        same repo on disk: True        mutually exclusive: False

    A caller reaching a repo through the symlink takes a lock that protects nothing
    while another process mutates the same working copy under the other key. That is
    precisely the failure this module exists to prevent, and both spellings are in
    live use: the fleet's own processes are launched under one and its projects table
    records the other.

    RESTORED 2026-09-04. This landed on 2026-09-03 as 2e8bb545 and then left the
    graph -- `git merge-base --is-ancestor 2e8bb545 master` says no, and
    `git log -S_canonical -- runner/repo_lock.py` on master finds nothing. The commit
    survives only as a dangling merge with a stash entry beside it. Nothing announced
    that; it surfaced because a test written against the fix started failing. The
    stranded-commit sentinel could not have caught it either: that scans local
    BRANCHES, and this is reachable from none.

    realpath, not abspath: abspath normalises `..` and a relative path but leaves a
    symlink alone, which is the exact case above. Falls back to the raw string if the
    path cannot be resolved, because a lock under an odd key still serialises the
    callers that share that key -- strictly better than raising inside a lock helper.
    """
    raw = str(repo or "unknown-repo")
    try:
        return os.path.realpath(raw) or raw
    except (OSError, ValueError):
        return raw


def _lock_path(repo):
    key = hashlib.sha1(_canonical(repo).encode()).hexdigest()[:16]
    return os.path.join(lock_dir(), f"repo-{key}.lock")


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


class StagingMoved(RuntimeError):
    """Raised when a paused lease is re-acquired and the ref it was gating has moved."""


class Lease:
    """A held repo lock that can be put down for a while and picked back up.

    WHY THIS EXISTS. The release train held a project's repo lock for its ENTIRE
    pass -- prewarm, QA suite, production build, pushes -- and for several projects
    at once. Measured 2026-09-03: one release train held the orchestrator's and
    smarter's locks for 43 minutes while running `npm run test`. The merge train
    waited, lost, and skipped the whole project group 607 times; merges were zero
    fleet-wide for three hours.

    The suite and the build do not need it. They run in `commit_overlay` scratch
    directories: the canonical repo is READ (git archive, then object reads through
    alternates) and never written.

    BUT THE LOCK WAS NOT ONLY PROTECTING THE WORKING COPY. It was also protecting
    the invariant that STAGING does not move between "we gated this SHA" and "we
    push it". Simply dropping it mid-pass would let another train advance staging
    while a twenty-minute suite ran, and the push would then promote a tip that was
    never gated -- a green proof for one commit and a different commit shipped.

    So a pause is not just an unlock. `paused(verify=...)` re-acquires on the way
    out and re-runs the caller's own check; if what it was gating has moved, it
    raises StagingMoved rather than letting the pass continue on a stale premise.
    Failing to re-acquire raises too. Neither is silent, because a lock helper that
    quietly hands back less protection than the caller asked for is the shape of
    bug this module keeps finding elsewhere.
    """

    def __init__(self, handle, repo, purpose=None):
        self._handle = handle
        self._repo = repo
        self._purpose = purpose
        self.acquired = False

    def __bool__(self):
        return bool(self.acquired)

    @contextlib.contextmanager
    def paused(self, verify=None, timeout=600):
        """Release the lock for the duration of the block, then take it back.

        `verify` is a zero-argument callable returning True when it is still safe to
        continue. It is called AFTER the lock is re-acquired, so it observes a
        settled state rather than racing the holder that had it in the meantime.
        """
        if not self.acquired:
            yield False          # never held it; nothing to put down
            return
        try:
            fcntl.flock(self._handle, fcntl.LOCK_UN)
            self.acquired = False
        except Exception as exc:
            log.error("repo_lock: could not release %s for a pause (%s) — keeping it",
                      self._repo, exc)
            yield False
            return
        try:
            yield True
        finally:
            deadline = time.time() + max(1.0, float(timeout))
            while time.time() < deadline:
                try:
                    fcntl.flock(self._handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.acquired = True
                    break
                except (BlockingIOError, OSError):
                    time.sleep(0.25)
            if not self.acquired:
                raise StagingMoved(
                    f"could not re-acquire the repo lock for {self._repo} within "
                    f"{timeout:.0f}s after pausing it; refusing to continue the pass "
                    f"unprotected")
            _write_holder(self._handle, self._repo, self._purpose)
            if verify is not None and not verify():
                raise StagingMoved(
                    f"{self._repo}: the ref this pass was gating moved while the lock "
                    f"was paused; the work that was verified is no longer the work that "
                    f"would ship")


@contextlib.contextmanager
def hold_pausable(repo, timeout=None, purpose=None):
    """Like hold(), but yields a Lease whose lock can be paused. See Lease.

    Separate from hold() on purpose: six callers use hold()'s yielded value as a
    plain boolean, and changing what they receive to buy one caller a feature is how
    a lock helper acquires a second, subtler contract nobody remembers.
    """
    lease = None
    try:
        os.makedirs(lock_dir(), exist_ok=True)
        handle = open(_lock_path(repo), "a+")
    except Exception as e:
        log.error("repo_lock: cannot open lock file under %s (%s: %s) — refusing the "
                  "lock for %s", lock_dir(), type(e).__name__, e, repo)
        yield Lease(None, repo)          # falsy
        return
    lease = Lease(handle, repo, purpose)
    try:
        if timeout:
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lease.acquired = True
                    break
                except (BlockingIOError, OSError):
                    time.sleep(0.25)
            if not lease.acquired:
                yield lease
                return
        else:
            fcntl.flock(handle, fcntl.LOCK_EX)
            lease.acquired = True
        _write_holder(handle, repo, purpose)
        yield lease
    finally:
        if lease is not None and lease.acquired:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            except Exception:
                pass
        try:
            handle.close()
        except Exception:
            pass


@contextlib.contextmanager
def hold(repo, timeout=None, purpose=None):
    """Exclusive lock scoped to `repo`. Yields True if the lock was acquired, False otherwise
    -- callers must skip their git-mutating work on False rather than proceed unprotected.

    False covers both reasons the lock is unavailable: another holder did not release within
    `timeout`, and the locking infrastructure itself is broken (uncreatable LOCK_DIR, disk
    full, permissions). The second used to yield True; see the module docstring for why that
    was the more expensive answer, not the cheaper one."""
    f = None
    try:
        os.makedirs(lock_dir(), exist_ok=True)
        f = open(_lock_path(repo), "a+")
    except Exception as e:
        # Loud, because the caller's retry will otherwise look like ordinary contention
        # forever and nothing will say the lock directory is the problem.
        log.error("repo_lock: cannot open lock file under %s (%s: %s) — refusing the lock "
                  "for %s; git-mutating work will be deferred, not run unprotected",
                  lock_dir(), type(e).__name__, e, repo)
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
