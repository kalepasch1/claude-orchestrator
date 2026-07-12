#!/usr/bin/env python3
"""
branch_repair_bot.py - automated branch management: detects missing branches,
resolves simple conflicts, and triggers merges for low-risk DONE tasks.

Runs periodically. For each DONE task whose agent/<slug> branch is missing
or has conflicts with the base branch, it takes remedial action:

  - Missing branch: marks the task for requeue with a recovery slug
  - Conflicting branch: attempts auto-rebase for low-risk (test/docs/chore) tasks
  - Clean branch: flags as merge-ready

Env vars:
    ORCH_BRANCH_REPAIR_BOT       "true" (default) to enable
    ORCH_BRANCH_REPAIR_DRY_RUN   "true" for dry-run mode (default: "true")
    ORCH_BRANCH_REPAIR_BATCH      max tasks per run (default: 10)
"""
import os, sys, subprocess, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("branch_repair_bot")
import db

ENABLED = os.environ.get("ORCH_BRANCH_REPAIR_BOT", "true").lower() in ("1", "true", "yes", "on")
DRY_RUN = os.environ.get("ORCH_BRANCH_REPAIR_DRY_RUN", "true").lower() in ("1", "true", "yes", "on")
BATCH_SIZE = int(os.environ.get("ORCH_BRANCH_REPAIR_BATCH", "10") or 10)

LOW_RISK_KINDS = {"test", "docs", "chore", "cleanup", "mechanical", "bugfix"}


def _git(repo, *args, timeout=30):
    """Run a git command, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo,
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def _branch_exists(repo, branch):
    rc, out, _ = _git(repo, "rev-parse", "--verify", branch)
    return rc == 0


def _has_conflicts(repo, base, branch):
    """Check if branch has conflicts with base via merge-tree."""
    rc, out, _ = _git(repo, "merge-tree", base, branch)
    if rc != 0:
        return True
    return "changed in both" in out.lower() or "CONFLICT" in out


def _auto_rebase(repo, base, branch):
    """Attempt non-interactive rebase. Returns True on success."""
    _git(repo, "checkout", branch)
    rc, _, err = _git(repo, "rebase", base, timeout=60)
    if rc != 0:
        _git(repo, "rebase", "--abort")
        return False
    return True


def _attempt_build_fix(repo, branch, build_log=""):
    """Attempt to fix simple build failures (missing imports, syntax)."""
    if not build_log:
        return False
    # Simple heuristic: if build log mentions ModuleNotFoundError for a known module,
    # check if sys.path insert is missing
    if "ModuleNotFoundError" in build_log or "ImportError" in build_log:
        _log.info(f"Build failure on {branch}: import error detected, marking for rework")
        return False  # cannot auto-fix; queue for rework
    return False


def scan_and_repair(repo_path, project_id):
    """Main entry: scan DONE tasks and repair branches."""
    if not ENABLED:
        return {"skipped": True, "reason": "disabled"}

    tasks = db.select("tasks", {
        "select": "id,slug,kind,base_branch,note",
        "project_id": project_id,
        "state": "DONE",
        "limit": BATCH_SIZE,
    }) or []

    results = []
    for t in tasks:
        slug = t.get("slug", "")
        branch = f"agent/{slug}"
        base = t.get("base_branch", "master")
        kind = t.get("kind", "")
        tid = t["id"]

        if not _branch_exists(repo_path, branch):
            _log.info(f"Branch missing for {slug}, marking for recovery")
            if not DRY_RUN:
                db.update("tasks", {
                    "state": "QUEUED",
                    "note": "branch_repair_bot: branch missing, requeued",
                    "slug": f"recover-{slug}" if not slug.startswith("recover-") else slug,
                }, {"id": tid})
            results.append({"slug": slug, "action": "requeued", "reason": "branch_missing"})
            continue

        if _has_conflicts(repo_path, base, branch):
            if kind in LOW_RISK_KINDS and not DRY_RUN:
                ok = _auto_rebase(repo_path, base, branch)
                if ok:
                    results.append({"slug": slug, "action": "rebased", "reason": "conflict_resolved"})
                else:
                    results.append({"slug": slug, "action": "skipped", "reason": "rebase_failed"})
            else:
                results.append({"slug": slug, "action": "skipped", "reason": "conflict_manual"})
            continue

        results.append({"slug": slug, "action": "clean", "reason": "merge_ready"})

    return {"checked": len(tasks), "results": results}
