#!/usr/bin/env python3
"""Serialize package-manager installs per checkout.

Why this exists
---------------
npm and pnpm are not safe to run concurrently against the same ``node_modules``. The fleet runs
installs from a dozen places (dependency_prewarm, toolchain_gate, error_remediation, merge_train,
build_daemon, root_cause, targeted_remedy, auto_conflict_resolver, runner, ...), and several
agents can be working the same checkout at once. When two installs interleave, one process
unpacks a package directory while the other prunes or rewrites it, and the tree is left with
package directories that exist but whose ``dist/`` is missing.

That failure is especially nasty because it is *silent*: ``node_modules/<pkg>`` and
``node_modules/.bin/<tool>`` both still exist, so readiness checks pass, and the build fails much
later with a misleading ``ERR_MODULE_NOT_FOUND`` for a transitive dependency. On 2026-08-02 this
corrupted ``citty``, ``h3``, ``std-env`` and ``consola`` in both the apparently and pareto-2080
checkouts and blocked their production builds.

``dependency_prewarm`` already had a lock, but it is keyed by *manifest content* so that identical
installs across worktrees collapse into one build. That is the right key for snapshot reuse and
the wrong key for mutual exclusion: two installs in the same checkout with different manifest
states (mid-edit, mid-merge, or one of the many callers that never touches prewarm at all) take
different locks and run straight through each other. This lock is keyed by the resolved checkout
path, which is the resource that actually needs protecting.

Usage
-----
    import install_lock
    with install_lock.hold(repo):
        subprocess.run([npm, "ci"], cwd=repo, ...)

``hold()`` never raises on lock-infrastructure problems — if flock is unavailable or the lock
directory cannot be created it logs and yields, because failing an install outright is worse than
running it unserialized.
"""
from __future__ import annotations

import contextlib
import errno
import os
import sys
import time

try:
    import fcntl
except Exception:  # pragma: no cover - non-POSIX
    fcntl = None

_RUNTIME = os.environ.get(
    "ORCH_RUNTIME",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime"),
)
_LOCK_DIR = os.path.join(_RUNTIME, "install-locks")

# An install of a large monorepo can legitimately take minutes. Wait well past that before
# assuming the holder is wedged.
DEFAULT_TIMEOUT_S = int(os.environ.get("ORCH_INSTALL_LOCK_TIMEOUT_S", "1800"))
_POLL_S = 0.5


def _key(repo: str) -> str:
    """Stable per-checkout key. Resolves symlinks so two paths to one tree share a lock."""
    try:
        real = os.path.realpath(repo)
    except Exception:
        real = repo or ""
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in real.strip("/"))
    return safe[-150:] or "unknown"


def lock_path(repo: str) -> str:
    return os.path.join(_LOCK_DIR, f"{_key(repo)}.lock")


def _log(msg: str) -> None:
    print(f"install_lock: {msg}", file=sys.stderr)


@contextlib.contextmanager
def hold(repo: str, timeout: int | None = None, reason: str = ""):
    """Hold the per-checkout install lock. Yields True if the lock was acquired.

    Yields (rather than raising) in every failure mode: an unserialized install is a risk, but a
    skipped install is a guaranteed broken build.
    """
    timeout = DEFAULT_TIMEOUT_S if timeout is None else timeout
    if fcntl is None or not repo:
        yield False
        return

    path = lock_path(repo)
    try:
        os.makedirs(_LOCK_DIR, exist_ok=True)
    except OSError as exc:
        _log(f"cannot create {_LOCK_DIR} ({exc}); proceeding unserialized")
        yield False
        return

    handle = None
    acquired = False
    try:
        handle = open(path, "a+")
        deadline = time.monotonic() + timeout
        waited_from = None
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if waited_from is None:
                    waited_from = time.monotonic()
                    _log(f"waiting for install lock on {repo}"
                         + (f" ({reason})" if reason else ""))
                if time.monotonic() >= deadline:
                    _log(f"timed out after {timeout}s waiting on {repo}; proceeding unserialized")
                    break
                time.sleep(_POLL_S)

        if acquired:
            if waited_from is not None:
                _log(f"acquired after {time.monotonic() - waited_from:.0f}s wait on {repo}")
            try:
                handle.seek(0)
                handle.truncate()
                handle.write(f"{os.getpid()} {int(time.time())} {reason}\n")
                handle.flush()
            except Exception:
                pass
        yield acquired
    except Exception as exc:  # never let lock plumbing fail an install
        _log(f"unexpected error ({exc}); proceeding unserialized")
        yield False
    finally:
        if handle is not None:
            try:
                if acquired:
                    fcntl.flock(handle, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                handle.close()
            except Exception:
                pass
