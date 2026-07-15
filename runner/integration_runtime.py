#!/usr/bin/env python3
"""Fail-closed runtime shared by Git merge and release trains."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import subprocess
import time


class IntegrationRuntimeError(RuntimeError):
    pass


class CanonicalCheckoutMutationError(IntegrationRuntimeError):
    pass


def _home():
    return os.environ.get(
        "CLAUDE_ORCH_HOME",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime"),
    )


def _git(repo, *args, timeout=120):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout)


def canonical_snapshot(repo):
    top = _git(repo, "rev-parse", "--show-toplevel")
    branch = _git(repo, "symbolic-ref", "-q", "HEAD")
    head = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    if top.returncode or head.returncode or status.returncode:
        raise IntegrationRuntimeError(f"cannot snapshot canonical Git checkout: {repo}")
    return {
        "top": os.path.realpath(top.stdout.strip()),
        "branch": branch.stdout.strip() if branch.returncode == 0 else "DETACHED",
        "head": head.stdout.strip(),
        "status": status.stdout,
    }


def _worktree_path(repo):
    key = hashlib.sha256(os.path.realpath(repo).encode()).hexdigest()[:20]
    return os.path.join(_home(), "integration-worktrees", key)


def _registered_worktrees(repo):
    result = _git(repo, "worktree", "list", "--porcelain")
    if result.returncode:
        return set()
    return {
        os.path.realpath(line.removeprefix("worktree ").strip())
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    }


@contextlib.contextmanager
def global_lease(owner, timeout=0):
    """One machine-wide lease for both merge_train and release_train."""
    path = os.path.join(_home(), "integration-trains.single.lock")
    handle = None
    acquired = False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handle = open(path, "a+")
        deadline = time.monotonic() + max(0.0, float(timeout or 0))
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, OSError):
                if not timeout or time.monotonic() >= deadline:
                    break
                time.sleep(0.1)
        if acquired:
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps({"pid": os.getpid(), "owner": owner, "at": time.time()}))
            handle.flush()
        yield acquired
    except OSError:
        yield False
    finally:
        if acquired and handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            except OSError:
                pass
        if handle:
            handle.close()


@contextlib.contextmanager
def isolated_repo(canonical_repo, owner):
    """Yield a clean detached integration worktree; never the canonical path."""
    canonical_repo = os.path.realpath(canonical_repo)
    before = canonical_snapshot(canonical_repo)
    path = _worktree_path(canonical_repo)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    registered = _registered_worktrees(canonical_repo)
    if os.path.exists(path) and os.path.realpath(path) not in registered:
        raise IntegrationRuntimeError(f"unregistered integration path exists: {path}")
    if not os.path.exists(path):
        added = _git(canonical_repo, "worktree", "add", "--detach", path, before["head"])
        if added.returncode or not os.path.isdir(path):
            raise IntegrationRuntimeError((added.stderr or added.stdout or "worktree add failed")[-1000:])
    actual = _git(path, "rev-parse", "--show-toplevel")
    branch = _git(path, "symbolic-ref", "-q", "HEAD")
    dirty = _git(path, "status", "--porcelain=v1", "--untracked-files=all")
    if actual.returncode or os.path.realpath(actual.stdout.strip()) != os.path.realpath(path):
        raise IntegrationRuntimeError("integration path is not the expected Git worktree")
    if branch.returncode == 0:
        raise IntegrationRuntimeError("integration worktree must remain detached")
    if dirty.returncode or dirty.stdout:
        raise IntegrationRuntimeError("integration worktree is dirty; refusing cleanup")
    positioned = _git(path, "checkout", "--detach", before["head"])
    if positioned.returncode:
        raise IntegrationRuntimeError((positioned.stderr or positioned.stdout)[-1000:])
    try:
        yield path
    finally:
        after = canonical_snapshot(canonical_repo)
        if after != before:
            raise CanonicalCheckoutMutationError(
                f"{owner} changed canonical checkout {canonical_repo}: {before} -> {after}"
            )
