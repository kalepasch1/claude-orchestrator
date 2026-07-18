"""Branch reconciler: reconciles local vs remote branches.

Identifies orphaned, stale, and conflicting branches without
hardcoded secrets. All config via environment variables.
"""

import os
import subprocess
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

# Config via env vars only — no hardcoded secrets
STALE_DAYS = int(os.environ.get("BRANCH_STALE_DAYS", "30"))
REMOTE_NAME = os.environ.get("GIT_REMOTE_NAME", "origin")
PROTECTED_BRANCHES = set(
    os.environ.get("PROTECTED_BRANCHES", "master,main,develop").split(",")
)


def _run_git(args: List[str], cwd: Optional[str] = None) -> str:
    """Run a git command and return stdout. Returns '' on error."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, timeout=30,
            cwd=cwd or os.getcwd(),
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def list_local_branches(cwd: Optional[str] = None) -> List[str]:
    """List all local branch names."""
    output = _run_git(["branch", "--format=%(refname:short)"], cwd=cwd)
    if not output:
        return []
    return [b.strip() for b in output.splitlines() if b.strip()]


def list_remote_branches(remote: Optional[str] = None,
                         cwd: Optional[str] = None) -> List[str]:
    """List all remote branch names (without remote/ prefix)."""
    r = remote or REMOTE_NAME
    output = _run_git(["branch", "-r", "--format=%(refname:short)"], cwd=cwd)
    if not output:
        return []
    prefix = f"{r}/"
    return [
        b.strip().removeprefix(prefix)
        for b in output.splitlines()
        if b.strip().startswith(prefix) and "HEAD" not in b
    ]


def get_branch_age_days(branch: str, cwd: Optional[str] = None) -> int:
    """Get the age in days of the last commit on a branch."""
    ts = _run_git(["log", "-1", "--format=%ct", branch], cwd=cwd)
    if not ts or not ts.isdigit():
        return -1
    commit_time = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    age = datetime.now(timezone.utc) - commit_time
    return age.days


def reconcile(cwd: Optional[str] = None) -> Dict[str, Any]:
    """Reconcile local vs remote branches.

    Returns a report with:
      - orphaned_local: local branches with no remote counterpart
      - orphaned_remote: remote branches with no local counterpart
      - stale: branches older than STALE_DAYS
      - conflicting: branches that exist both locally and remotely
                     but have diverged
      - protected: branches that are protected (informational)
    """
    local = set(list_local_branches(cwd=cwd))
    remote = set(list_remote_branches(cwd=cwd))
    orphaned_local = sorted(local - remote - PROTECTED_BRANCHES)
    orphaned_remote = sorted(remote - local - PROTECTED_BRANCHES)
    common = local & remote
    stale = []
    for b in sorted(local | remote):
        if b in PROTECTED_BRANCHES:
            continue
        age = get_branch_age_days(b, cwd=cwd)
        if age >= STALE_DAYS:
            stale.append({"branch": b, "age_days": age})
    conflicting = []
    for b in sorted(common):
        if b in PROTECTED_BRANCHES:
            continue
        local_sha = _run_git(["rev-parse", b], cwd=cwd)
        remote_sha = _run_git(
            ["rev-parse", f"{REMOTE_NAME}/{b}"], cwd=cwd
        )
        if local_sha and remote_sha and local_sha != remote_sha:
            conflicting.append({
                "branch": b,
                "local_sha": local_sha[:10],
                "remote_sha": remote_sha[:10],
            })
    return {
        "orphaned_local": orphaned_local,
        "orphaned_remote": orphaned_remote,
        "stale": stale,
        "conflicting": conflicting,
        "protected": sorted(PROTECTED_BRANCHES & (local | remote)),
        "total_local": len(local),
        "total_remote": len(remote),
    }
