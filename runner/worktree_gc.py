"""worktree_gc.py — automated worktree garbage collection.

Wraps branch_hygiene to provide a safe, dry-run-first garbage collector
for stale worktrees and merged agent branches. Intended to be called by
scheduled sweeps or the operator CLI.

Safety: dry_run=True by default. Locked worktrees are never removed.
Fail-soft: individual removal failures are logged, not raised.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class GCResult:
    """Result of a garbage collection run."""
    worktrees_removed: List[str]
    branches_deleted: List[str]
    errors: List[str]
    dry_run: bool

    @property
    def summary(self) -> str:
        mode = "DRY RUN" if self.dry_run else "APPLIED"
        return (f"[{mode}] removed {len(self.worktrees_removed)} worktrees, "
                f"deleted {len(self.branches_deleted)} branches, "
                f"{len(self.errors)} errors")


def _run_git(repo: str, *args: str, timeout: int = 30) -> Optional[str]:
    try:
        r = subprocess.run(
            ["git", "-C", repo] + list(args),
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout if r.returncode == 0 else None
    except Exception as exc:
        logger.warning("worktree_gc git failed: %s", exc)
        return None


def collect_gc(repo: str, dry_run: bool = True) -> GCResult:
    """Identify and optionally remove stale worktrees and merged branches.

    1. Removes worktrees that are prunable, detached+unlocked, or whose
       branch is already merged to the target.
    2. Deletes local agent/* branches that are merged.

    Set dry_run=False to actually perform removals.
    """
    try:
        import branch_hygiene as bh
    except ImportError:
        return GCResult([], [], ["branch_hygiene not importable"], dry_run)

    result = GCResult([], [], [], dry_run)

    stale = bh.stale_worktrees(repo)
    for entry in stale:
        if entry.is_locked:
            continue
        if dry_run:
            result.worktrees_removed.append(entry.path)
            logger.info("DRY RUN: would remove worktree %s", entry.path)
        else:
            out = _run_git(repo, "worktree", "remove", "--force", entry.path)
            if out is not None:
                result.worktrees_removed.append(entry.path)
                logger.info("removed worktree %s", entry.path)
            else:
                result.errors.append(f"failed to remove {entry.path}")

    merged = bh.merged_agent_branches(repo)
    for branch in merged:
        if dry_run:
            result.branches_deleted.append(branch)
            logger.info("DRY RUN: would delete branch %s", branch)
        else:
            out = _run_git(repo, "branch", "-d", branch)
            if out is not None:
                result.branches_deleted.append(branch)
            else:
                result.errors.append(f"failed to delete {branch}")

    logger.info(result.summary)
    return result
