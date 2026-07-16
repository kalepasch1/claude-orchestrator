#!/usr/bin/env python3
"""
stale_branch_lister.py — List remote branches with no commits in the last N days.

Uses subprocess + git to enumerate remote branches and their last commit dates,
avoiding a hard dependency on gitpython. Falls back gracefully if git is unavailable.

Env vars:
    ORCH_STALE_DAYS    Days since last commit to consider stale (default 90)
    ORCH_REMOTE        Remote name to inspect (default "origin")

Usage:
    python3 stale_branch_lister.py [repo_path]
"""
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import log as _log_mod
    _log = _log_mod.get("stale_branch_lister")
except Exception:
    import logging
    _log = logging.getLogger("stale_branch_lister")

STALE_DAYS = int(os.environ.get("ORCH_STALE_DAYS", "90"))
REMOTE = os.environ.get("ORCH_REMOTE", "origin")

def list_remote_branches(repo_path, remote=None):
    """Return list of (branch_name, last_commit_iso) for all remote branches."""
    remote = remote or REMOTE
    try:
        raw = subprocess.check_output(
            ["git", "for-each-ref",
             f"refs/remotes/{remote}/",
             "--sort=-committerdate",
             "--format=%(refname:short)\t%(committerdate:iso8601)"],
            cwd=repo_path, timeout=30, text=True, stderr=subprocess.DEVNULL
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        _log.warning("Could not list remote branches: %s", e)
        return []

    branches = []
    for line in raw.strip().splitlines():
        if not line or "\t" not in line:
            continue
        name, date_str = line.split("\t", 1)
        # Strip remote prefix (e.g. "origin/agent/foo" -> "agent/foo")
        prefix = f"{remote}/"
        if name.startswith(prefix):
            name = name[len(prefix):]
        branches.append((name, date_str.strip()))
    return branches


def filter_stale(branches, stale_days=None):
    """Return only branches whose last commit is older than stale_days."""
    stale_days = stale_days if stale_days is not None else STALE_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
    stale = []
    for name, date_str in branches:
        try:
            # Parse git iso8601 format: "2026-01-15 10:30:00 -0400"
            dt = datetime.fromisoformat(date_str.replace(" -", "-").replace(" +", "+"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < cutoff:
                stale.append({"branch": name, "last_commit": date_str, "age_days": (datetime.now(timezone.utc) - dt).days})
        except (ValueError, TypeError):
            _log.debug("Could not parse date for branch %s: %s", name, date_str)
    return stale


def list_stale_branches(repo_path, stale_days=None, remote=None):
    """Main entry: list stale remote branches for a repo."""
    branches = list_remote_branches(repo_path, remote=remote)
    stale = filter_stale(branches, stale_days=stale_days)
    _log.info("Found %d stale branches (>%d days) out of %d total", len(stale), stale_days or STALE_DAYS, len(branches))
    return stale


if __name__ == "__main__":
    import json
    repo = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    days = int(sys.argv[2]) if len(sys.argv) > 2 else STALE_DAYS
    stale = list_stale_branches(repo, stale_days=days)
    print(json.dumps(stale, indent=2))
    print(f"\n{len(stale)} stale branches (>{days} days)")
