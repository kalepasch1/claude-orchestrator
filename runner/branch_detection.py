#!/usr/bin/env python3
"""
branch_detection.py — detect orphaned, missing, and diverged agent branches.

Provides utilities for automated branch recovery workflows:
  - detect_orphaned_branches: branches with no matching task
  - detect_missing_branches: tasks whose branches don't exist
  - detect_diverged_branches: branches that have diverged from base
  - classify_branch_state: single-branch health classifier

Used by branch_fleet_recovery and the merge train to identify
branches needing intervention before they block the pipeline.

Env vars:
    ORCH_BRANCH_DETECT_TIMEOUT   git command timeout in seconds (default 30)
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TIMEOUT = int(os.environ.get("ORCH_BRANCH_DETECT_TIMEOUT", "30"))


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
def _git(repo, *args):
    """Run a git command, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            ["git"] + list(args), cwd=repo,
            capture_output=True, text=True, timeout=TIMEOUT,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def _list_agent_branches(repo_path):
    """Return set of agent branch names (without 'agent/' prefix)."""
    rc, out, _ = _git(repo_path, "branch", "--list", "agent/*")
    if rc != 0 or not out:
        return set()
    return {
        b.strip().lstrip("* ").replace("agent/", "", 1)
        for b in out.splitlines()
        if b.strip()
    }


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------
def detect_orphaned_branches(repo_path, known_slugs):
    """Find agent branches that have no matching task slug.

    Parameters
    ----------
    repo_path : str
        Path to the git repository.
    known_slugs : set | list
        Slugs of all known tasks (any state).

    Returns
    -------
    list[str]
        Slugs of orphaned branches.
    """
    if not repo_path or not os.path.isdir(repo_path):
        return []
    known = set(known_slugs) if known_slugs else set()
    branches = _list_agent_branches(repo_path)
    return sorted(b for b in branches if b not in known)


def detect_missing_branches(repo_path, tasks):
    """Find tasks whose expected agent branches don't exist.

    Parameters
    ----------
    repo_path : str
        Path to the git repository.
    tasks : list[dict]
        Task dicts with at least 'slug' and 'state' keys.

    Returns
    -------
    list[dict]
        Tasks that are in an active state but have no branch.
    """
    if not repo_path or not os.path.isdir(repo_path):
        return []
    active_states = {"QUEUED", "RUNNING", "BLOCKED", "IN_PROGRESS"}
    branches = _list_agent_branches(repo_path)
    missing = []
    for task in (tasks or []):
        slug = task.get("slug", "")
        state = task.get("state", "")
        if state in active_states and slug and slug not in branches:
            missing.append(task)
    return missing


def detect_diverged_branches(repo_path, branches, base="master", threshold=100):
    """Find branches that have diverged more than *threshold* commits behind base.

    Returns list of dicts with 'branch', 'behind', 'ahead'.
    """
    if not repo_path or not os.path.isdir(repo_path):
        return []
    diverged = []
    for branch in (branches or []):
        full = f"agent/{branch}" if not branch.startswith("agent/") else branch
        rc, out, _ = _git(repo_path, "rev-list", "--left-right", "--count",
                          f"{base}...{full}")
        if rc != 0 or not out:
            continue
        parts = out.split()
        if len(parts) != 2:
            continue
        try:
            behind, ahead = int(parts[0]), int(parts[1])
        except (ValueError, TypeError):
            continue
        if behind > threshold:
            diverged.append({"branch": full, "behind": behind, "ahead": ahead})
    return diverged


def classify_branch_state(repo_path, slug, known_slugs=None, tasks=None):
    """Classify a single branch into one of: healthy, orphaned, missing, unknown.

    Returns a dict with 'slug', 'state', and 'detail'.
    """
    full_branch = f"agent/{slug}"
    rc, _, _ = _git(repo_path, "rev-parse", "--verify", full_branch)
    branch_exists = (rc == 0)

    known = set(known_slugs) if known_slugs else set()
    task_slugs = {t.get("slug") for t in (tasks or [])}

    if branch_exists and slug in (known or task_slugs):
        return {"slug": slug, "state": "healthy", "detail": "branch and task both exist"}
    if branch_exists and slug not in (known or task_slugs):
        return {"slug": slug, "state": "orphaned", "detail": "branch exists but no task found"}
    if not branch_exists and slug in task_slugs:
        return {"slug": slug, "state": "missing", "detail": "task exists but branch is missing"}
    return {"slug": slug, "state": "unknown", "detail": "neither branch nor task found"}
