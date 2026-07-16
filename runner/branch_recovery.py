#!/usr/bin/env python3
"""
branch_recovery.py — AI-assisted branch management and recovery.

Automates the most common missing-branch recovery patterns:
1. Local branch exists but was never pushed → push it
2. Remote branch exists but local is stale → fetch and update
3. Stale worktree holds the branch → prune and recreate
4. Reflog has evidence of the branch → cherry-pick recovery
5. No trace found → signal for full reconstruction

Called by autopilot's recovery_agent and by agentic_repair when
category='missing-branch'. Reduces manual intervention for conflict
resolution and branch management delays.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RECOVERY_TIMEOUT = int(os.environ.get("ORCH_BRANCH_RECOVERY_TIMEOUT", "30"))


def _git(args, cwd, timeout=None):
    """Run a git command and return (returncode, stdout, stderr)."""
    timeout = timeout or RECOVERY_TIMEOUT
    try:
        r = subprocess.run(
            ["git"] + args, cwd=cwd,
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def diagnose(slug, repo_path):
    """Diagnose a missing branch and return recovery plan.

    Returns dict:
        status: 'local' | 'remote' | 'worktree' | 'reflog' | 'gone'
        branch: str  — the full branch name
        action: str  — recommended recovery action
        details: str — human-readable explanation
    """
    branch = f"agent/{slug}"
    result = {"status": "gone", "branch": branch, "action": "reconstruct", "details": ""}

    # 1. Check local branches
    rc, out, _ = _git(["branch", "--list", branch], repo_path)
    if rc == 0 and out.strip():
        # Verify it has commits ahead of base
        rc2, ahead, _ = _git(["rev-list", "--count", f"HEAD..{branch}"], repo_path)
        commits = int(ahead) if rc2 == 0 and ahead.isdigit() else 0
        result.update(
            status="local",
            action="push",
            details=f"Local branch exists with {commits} commit(s) ahead — push to remote.",
        )
        return result

    # 2. Check remote
    rc, out, _ = _git(["ls-remote", "--heads", "origin", branch], repo_path)
    if rc == 0 and out.strip():
        result.update(
            status="remote",
            action="fetch",
            details="Branch exists on remote — fetch and create local tracking branch.",
        )
        return result

    # 3. Check stale worktrees
    rc, out, _ = _git(["worktree", "list", "--porcelain"], repo_path)
    if rc == 0:
        for line in out.split("\n"):
            if line.startswith("branch ") and slug in line:
                result.update(
                    status="worktree",
                    action="prune_and_recover",
                    details="Branch is checked out in a stale worktree — prune first.",
                )
                return result

    # 4. Check reflog
    rc, out, _ = _git(["reflog", "--all", "--grep-reflog", slug, "--format=%H"], repo_path)
    if rc == 0 and out.strip():
        shas = [s for s in out.split("\n") if s.strip()]
        result.update(
            status="reflog",
            action="cherry_pick",
            details=f"Found {len(shas)} reflog entries — recover via cherry-pick from {shas[0][:8]}.",
        )
        return result

    result["details"] = "No trace of branch found — full reconstruction required."
    return result


def recover(slug, repo_path, base_branch="master"):
    """Attempt automatic recovery of a missing branch.

    Returns dict:
        recovered: bool
        method: str
        branch: str
        details: str
    """
    diag = diagnose(slug, repo_path)
    branch = diag["branch"]
    out = {"recovered": False, "method": diag["action"], "branch": branch, "details": ""}

    if diag["status"] == "local":
        # Just push it
        rc, stdout, stderr = _git(["push", "origin", f"{branch}:{branch}", "--force"], repo_path)
        if rc == 0:
            out.update(recovered=True, details="Pushed existing local branch to remote.")
        else:
            out["details"] = f"Push failed: {stderr[:200]}"
        return out

    if diag["status"] == "remote":
        # Fetch and create local
        rc, _, stderr = _git(["fetch", "origin", f"{branch}:{branch}"], repo_path)
        if rc == 0:
            out.update(recovered=True, details="Fetched remote branch to local.")
        else:
            out["details"] = f"Fetch failed: {stderr[:200]}"
        return out

    if diag["status"] == "worktree":
        # Prune stale worktrees then retry
        _git(["worktree", "prune"], repo_path)
        # Check if branch is now accessible
        rc, _, _ = _git(["rev-parse", "--verify", branch], repo_path)
        if rc == 0:
            out.update(recovered=True, method="prune_and_recover",
                       details="Pruned stale worktree — branch is now accessible.")
        else:
            out["details"] = "Pruned worktree but branch ref was already deleted."
        return out

    if diag["status"] == "reflog":
        # Create branch from reflog SHA
        rc, sha, _ = _git(["reflog", "--all", "--grep-reflog", slug, "--format=%H", "-1"], repo_path)
        if rc == 0 and sha:
            rc2, _, stderr = _git(["branch", "-f", branch, sha], repo_path)
            if rc2 == 0:
                out.update(recovered=True, method="cherry_pick",
                           details=f"Recreated branch from reflog at {sha[:8]}.")
            else:
                out["details"] = f"Branch creation from reflog failed: {stderr[:200]}"
        return out

    out["details"] = diag["details"]
    return out


def batch_recover(slugs, repo_path, base_branch="master"):
    """Recover multiple missing branches. Returns summary dict."""
    results = {}
    recovered = 0
    for slug in slugs:
        r = recover(slug, repo_path, base_branch)
        results[slug] = r
        if r["recovered"]:
            recovered += 1
    return {
        "total": len(slugs),
        "recovered": recovered,
        "failed": len(slugs) - recovered,
        "details": results,
    }
