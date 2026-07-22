#!/usr/bin/env python3
"""
branch_preflight.py - detect missing branches at the start of each merge cycle.

Before approval_merge begins integrating approved tasks, this module checks
that every task's expected agent branch still exists in the repo.  Missing
branches (force-deleted, garbage-collected, or never pushed) are flagged
immediately so the merge cycle can skip or re-queue them instead of failing
mid-way through a rebase.

Usage (called by approval_merge at cycle start):
    import branch_preflight
    missing = branch_preflight.check(repo_path, tasks)
    # missing: list of (task_id, slug, expected_branch)

Fail-soft: returns [] on any error so the merge cycle always proceeds.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import branch_naming

AUTO_BLOCK = os.environ.get("ORCH_BRANCH_PREFLIGHT_AUTO_BLOCK", "true").lower() in ("1", "true", "yes")


def _branch_exists(repo_path, branch):
    """Check whether branch exists locally or in any remote."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--verify", branch],
            cwd=repo_path, capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            return True
        r2 = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", branch],
            cwd=repo_path, capture_output=True, text=True, timeout=15,
        )
        return bool(r2.stdout.strip())
    except Exception:
        return True


def check(repo_path, tasks):
    """Return list of (task_id, slug, expected_branch) for tasks whose branch is missing."""
    if not repo_path or not tasks:
        return []
    try:
        subprocess.run(["git", "fetch", "--prune", "origin"],
                       cwd=repo_path, capture_output=True, timeout=30)
    except Exception:
        pass
    missing = []
    for task in tasks:
        try:
            slug = task.get("slug", "")
            task_id = task.get("id", "")
            if not slug:
                continue
            expected = branch_naming.get_agent_branch_name(slug)
            if not _branch_exists(repo_path, expected):
                missing.append((task_id, slug, expected))
        except Exception:
            continue
    return missing


def check_and_block(repo_path, tasks):
    """Check for missing branches and optionally BLOCK those tasks in the DB."""
    missing = check(repo_path, tasks)
    if not missing or not AUTO_BLOCK:
        return missing
    try:
        import db
        for task_id, slug, branch in missing:
            db.update_task(task_id, {
                "state": "BLOCKED",
                "note": f"branch_preflight: branch '{branch}' missing at merge-cycle start",
            })
    except Exception:
        pass
    return missing


def stats():
    return {}
