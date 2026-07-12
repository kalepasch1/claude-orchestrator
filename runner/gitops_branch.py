#!/usr/bin/env python3
"""
gitops_branch.py - GitOps-driven branch lifecycle management.

Automates branch creation, cleanup, and state tracking via DB.

Env:
    ORCH_GITOPS_ENABLED    (default "true")
    ORCH_BRANCH_TTL_DAYS   (default "7")
    ORCH_BRANCH_PREFIX     (default "agent/")
"""
import os, sys, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_ENABLED = os.environ.get("ORCH_GITOPS_ENABLED", "true").lower() in ("true", "1")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TTL_DAYS = int(os.environ.get("ORCH_BRANCH_TTL_DAYS", "7"))
PREFIX = os.environ.get("ORCH_BRANCH_PREFIX", "agent/")


def _git(*args, cwd=None, timeout=60):
    try:
        r = subprocess.run(["git", *args], cwd=cwd or REPO,
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1


def list_agent_branches() -> list:
    """List all local branches matching the agent prefix."""
    if not _ENABLED:
        return []
    try:
        out, rc = _git("branch", "--list", f"{PREFIX}*", "--format=%(refname:short)")
        return [b.strip() for b in out.splitlines() if b.strip()] if rc == 0 else []
    except Exception:
        return []


def branch_age_days(branch: str) -> float:
    """Return age of last commit on branch in days. -1 on error."""
    try:
        out, rc = _git("log", "-1", "--format=%ct", branch)
        return (time.time() - float(out)) / 86400 if rc == 0 else -1
    except Exception:
        return -1


def is_merged(branch: str, target: str = "master") -> bool:
    """Check if branch is fully merged into target."""
    try:
        out, rc = _git("branch", "--merged", target, "--list", branch)
        return bool(out.strip())
    except Exception:
        return False


def find_stale_branches(ttl_days: int = None) -> list:
    """Return agent branches older than TTL that are already merged."""
    ttl = ttl_days if ttl_days is not None else TTL_DAYS
    stale = []
    for b in list_agent_branches():
        age = branch_age_days(b)
        if age > ttl and is_merged(b):
            stale.append({"branch": b, "age_days": round(age, 1), "merged": True})
    return stale


def cleanup_stale(dry_run: bool = True) -> list:
    """Delete stale merged branches. dry_run=True only reports. Fail-soft."""
    if not _ENABLED:
        return []
    actions = []
    for info in find_stale_branches():
        branch = info["branch"]
        if dry_run:
            actions.append({"action": "would_delete", **info})
        else:
            _, rc = _git("branch", "-d", branch)
            status = "deleted" if rc == 0 else "delete_failed"
            actions.append({"action": status, **info})
            try:
                db.insert("fleet_config", {"key": f"GITOPS_AUDIT_{int(time.time())}",
                    "value": f"{status}: {branch} (age={info['age_days']}d)"})
            except Exception:
                pass
    return actions


def reconcile() -> dict:
    """Full reconciliation pass. Returns summary. Fail-soft."""
    if not _ENABLED:
        return {"enabled": False}
    try:
        branches = list_agent_branches()
        stale = find_stale_branches()
        return {"total_agent_branches": len(branches), "stale_count": len(stale),
                "stale": stale[:10]}
    except Exception as e:
        return {"error": str(e)}
