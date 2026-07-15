#!/usr/bin/env python3
"""Fail-closed task worktree creation and validation."""
from __future__ import annotations

import os
import subprocess

import repo_lock


class WorktreeIsolationError(RuntimeError):
    """An isolated task checkout could not be proven safe."""


def task_worktree_path(repo: str, slug: str) -> str:
    repo = os.path.realpath(repo)
    return os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", slug)


def _git(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, timeout=120
    )


def validate_task_worktree(repo: str, slug: str, worktree: str | None = None) -> str:
    repo = os.path.realpath(repo)
    wt = os.path.realpath(worktree or task_worktree_path(repo, slug))
    if wt == repo:
        raise WorktreeIsolationError("task worktree resolved to the primary checkout")
    if not os.path.isdir(wt):
        raise WorktreeIsolationError(f"task worktree is missing: {wt}")

    top = _git(wt, "rev-parse", "--show-toplevel")
    if top.returncode or os.path.realpath(top.stdout.strip()) != wt:
        raise WorktreeIsolationError("task path is not the expected git worktree")

    branch = _git(wt, "symbolic-ref", "--quiet", "--short", "HEAD")
    expected = f"agent/{slug}"
    if branch.returncode or branch.stdout.strip() != expected:
        actual = branch.stdout.strip() or "detached/unknown"
        raise WorktreeIsolationError(
            f"task worktree branch mismatch: expected {expected}, found {actual}"
        )

    listed = _git(repo, "worktree", "list", "--porcelain")
    registered = {
        os.path.realpath(line.removeprefix("worktree ").strip())
        for line in listed.stdout.splitlines()
        if line.startswith("worktree ")
    }
    if listed.returncode or wt not in registered:
        raise WorktreeIsolationError("task worktree is not registered by the primary repository")
    return wt


def ensure_task_worktree(repo: str, slug: str, base: str, setup_script: str) -> str:
    """Create or reuse a task worktree while holding the repository lock."""
    wt = task_worktree_path(repo, slug)
    with repo_lock.hold(repo, timeout=120) as acquired:
        if not acquired:
            raise WorktreeIsolationError("repository isolation lock unavailable")

        # Preserve interrupted work. Never reset or clean an existing valid checkout.
        if os.path.isdir(wt):
            return validate_task_worktree(repo, slug, wt)

        created = subprocess.run(
            [setup_script, slug, base], cwd=repo, capture_output=True, text=True, timeout=300
        )
        if created.returncode:
            detail = (created.stderr or created.stdout or "unknown setup error").strip()[-1000:]
            raise WorktreeIsolationError(f"worktree setup failed: {detail}")
        return validate_task_worktree(repo, slug, wt)
