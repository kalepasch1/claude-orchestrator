#!/usr/bin/env python3
"""Fail-closed task worktree creation and validation."""
from __future__ import annotations

import os
import subprocess

import repo_lock
from typing import Optional


class WorktreeIsolationError(RuntimeError):
    """An isolated task checkout could not be proven safe."""


def task_worktree_path(repo: str, slug: str) -> str:
    repo = os.path.realpath(repo)
    return os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", slug)


def owner_marker_path(repo: str, slug: str) -> str:
    wt_root = os.path.dirname(task_worktree_path(repo, slug))
    return os.path.join(wt_root, ".orchestrator-owners", slug)


def validate_owner(repo: str, slug: str, task_id: str, lease_token: str) -> None:
    try:
        with open(owner_marker_path(repo, slug), encoding="utf-8") as marker:
            lines = [line.rstrip("\n") for line in marker.readlines()[:3]]
    except OSError as exc:
        raise WorktreeIsolationError("worktree owner marker is missing") from exc
    if lines[:2] != [task_id, lease_token]:
        raise WorktreeIsolationError("worktree is owned by another task or lease")


def _git(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, timeout=120
    )


def is_nested_in(child: str, parent: str) -> bool:
    """True if `child` lives inside `parent` (not equal to it)."""
    child = os.path.realpath(child)
    parent = os.path.realpath(parent)
    if child == parent:
        return False
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:  # different drives / unrelated roots
        return False


def validate_task_worktree(repo: str, slug: str, worktree: Optional[str] = None) -> str:
    repo = os.path.realpath(repo)
    wt = os.path.realpath(worktree or task_worktree_path(repo, slug))
    if wt == repo:
        raise WorktreeIsolationError("task worktree resolved to the primary checkout")
    # A worktree nested inside the primary checkout is never valid, even though it
    # "works" at first. When it is later pruned, its .git gitlink dangles and breaks
    # `git status` repo-wide (fatal: not a git repository), which silently disables
    # the sentinel's own dirty-check and the merge pipeline. It also gets swept by
    # stash and can be committed as a gitlink. Observed 2026-07-16 with
    # claude-orchestrator/claude-orchestrator-wt/agent-cade-inbound-triage.
    if is_nested_in(wt, repo):
        raise WorktreeIsolationError(
            f"task worktree must be a sibling of the primary checkout, not nested inside it: {wt}"
        )
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


def ensure_task_worktree(repo: str, slug: str, base: str, setup_script: str, *,
                         task_id: Optional[str] = None, lease_token: Optional[str] = None) -> str:
    """Create or reuse a task worktree while holding the repository lock."""
    wt = task_worktree_path(repo, slug)
    with repo_lock.hold(repo, timeout=120) as acquired:
        if not acquired:
            raise WorktreeIsolationError("repository isolation lock unavailable")

        if not task_id or not lease_token:
            raise WorktreeIsolationError("task and branch-lease identity are required")

        # Preserve interrupted work only for the exact still-leased writer.
        # A matching branch name is not ownership proof.
        if os.path.isdir(wt):
            validate_owner(repo, slug, task_id, lease_token)
            return validate_task_worktree(repo, slug, wt)

        created = subprocess.run(
            [setup_script, slug, base, task_id, lease_token],
            cwd=repo, capture_output=True, text=True, timeout=300,
        )
        if created.returncode:
            detail = (created.stderr or created.stdout or "unknown setup error").strip()[-1000:]
            raise WorktreeIsolationError(f"worktree setup failed: {detail}")
        validate_owner(repo, slug, task_id, lease_token)
        return validate_task_worktree(repo, slug, wt)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Create and validate one isolated task worktree")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--lease-token", required=True)
    parser.add_argument(
        "--setup-script", default=os.path.join(os.path.dirname(__file__), "setup-worktrees.sh")
    )
    args = parser.parse_args()
    try:
        print(ensure_task_worktree(
            args.repo, args.slug, args.base, args.setup_script,
            task_id=args.task_id, lease_token=args.lease_token,
        ))
        return 0
    except WorktreeIsolationError as exc:
        print(f"worktree isolation failed: {exc}", file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
