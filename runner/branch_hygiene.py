"""branch_hygiene.py — identify stale agent worktrees and branches for cleanup.

GitOps convention: agent work lives in isolated worktrees under {repo}-wt/{slug}.
Worktrees are removed after push; the agent/{slug} branch persists for merge-train
pickup.  In practice worktrees accumulate — failed runs, interrupted sessions, or
branches already merged to orchestrator/dev that nobody pruned.

This module provides lightweight checks so the operator (or a scheduled sweep) can
list what is safe to remove without grepping the home directory.

Fail-soft throughout: a bad worktree entry or an unreadable git dir yields a warning
and fewer results, never an exception.
"""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class WorktreeEntry:
    """One parsed line from ``git worktree list --porcelain``."""
    path: str = ""
    head: str = ""
    branch: str = ""
    is_bare: bool = False
    is_detached: bool = False
    is_locked: bool = False
    is_prunable: bool = False


def _run_git(repo: str, *args: str, timeout: int = 30) -> Optional[str]:
    """Run a git command in *repo*, returning stdout or None on any failure."""
    try:
        r = subprocess.run(
            ["git", "-C", repo] + list(args),
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout if r.returncode == 0 else None
    except Exception as exc:
        logger.warning("git command failed in %s: %s", repo, exc)
        return None


def list_worktrees(repo: str) -> List[WorktreeEntry]:
    """Parse ``git worktree list --porcelain`` into structured entries."""
    raw = _run_git(repo, "worktree", "list", "--porcelain")
    if not raw:
        return []
    entries: List[WorktreeEntry] = []
    current = WorktreeEntry()
    for line in raw.splitlines():
        if not line.strip():
            if current.path:
                entries.append(current)
            current = WorktreeEntry()
            continue
        if line.startswith("worktree "):
            current.path = line[9:]
        elif line.startswith("HEAD "):
            current.head = line[5:]
        elif line.startswith("branch "):
            current.branch = line[7:]
        elif line == "bare":
            current.is_bare = True
        elif line == "detached":
            current.is_detached = True
        elif line.startswith("locked"):
            current.is_locked = True
        elif line.startswith("prunable"):
            current.is_prunable = True
    if current.path:
        entries.append(current)
    return entries


def merged_agent_branches(repo: str, target: str = "master") -> List[str]:
    """Return agent/* branches already merged into *target*."""
    raw = _run_git(repo, "branch", "--merged", target, "--list", "agent/*")
    if not raw:
        return []
    return [b.strip().lstrip("* ") for b in raw.splitlines() if b.strip()]


def stale_worktrees(repo: str) -> List[WorktreeEntry]:
    """Worktrees that are prunable, detached, or whose branch is already merged."""
    entries = list_worktrees(repo)
    merged = set(merged_agent_branches(repo))
    stale: List[WorktreeEntry] = []
    for e in entries:
        if e.is_bare:
            continue
        branch_short = e.branch.replace("refs/heads/", "")
        if e.is_prunable:
            stale.append(e)
        elif e.is_detached and not e.is_locked:
            stale.append(e)
        elif branch_short in merged and not e.is_locked:
            stale.append(e)
    return stale


def cleanup_report(repo: str) -> dict:
    """Summary dict for operator dashboards. Fail-soft: returns empty on error."""
    try:
        all_wt = list_worktrees(repo)
        stale = stale_worktrees(repo)
        merged = merged_agent_branches(repo)
        return {
            "total_worktrees": len(all_wt),
            "stale_worktrees": len(stale),
            "merged_agent_branches": len(merged),
            "stale_paths": [e.path for e in stale],
            "merged_branches": merged,
        }
    except Exception as exc:
        logger.warning("cleanup_report failed for %s: %s", repo, exc)
        return {}
