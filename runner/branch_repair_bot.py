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
    rc, _, _ = _git(repo, "rev-parse", "--verify", branch)
    return rc == 0


def _has_conflicts(repo, branch, base):
    """Check if branch has merge conflicts with base (without modifying worktree)."""
    rc, merge_base, _ = _git(repo, "merge-base", base, branch)
    if rc != 0:
        return None  # can't determine
    rc, _, _ = _git(repo, "merge-tree", merge_base, base, branch)
    return rc != 0


def _is_clean_merge(repo, branch, base):
    """Check if branch merges cleanly into base."""
    conflicts = _has_conflicts(repo, branch, base)
    if conflicts is None:
        return None
    return not conflicts


def check_task(task, repo):
    """Check a single task's branch status. Returns a status dict."""
    slug = task.get("slug", "")
    branch = f"agent/{slug}"
    base = task.get("base_branch", "master")
    kind = task.get("kind", "")

    result = {
        "task_id": task["id"],
        "slug": slug,
        "branch": branch,
        "status": "unknown",
        "action": "none",
    }

    if not _branch_exists(repo, branch):
        result["status"] = "missing"
        result["action"] = "requeue"
        return result

    clean = _is_clean_merge(repo, branch, base)
    if clean is None:
        result["status"] = "check_failed"
        result["action"] = "manual"
    elif clean:
        result["status"] = "clean"
        result["action"] = "merge_ready"
    else:
        result["status"] = "conflicts"
        result["action"] = "rebase" if kind in LOW_RISK_KINDS else "manual"

    return result


def repair_task(task, repo, result):
    """Take remedial action based on check result. Returns updated result."""
    if DRY_RUN:
        _log.info("[DRY RUN] would %s task %s (%s)", result["action"], result["slug"], result["status"])
        result["executed"] = False
        return result

    action = result["action"]
    slug = result["slug"]

    if action == "requeue":
        recovery_slug = f"{db.RECOVERY_PREFIX}{slug}"[:80]
        _log.info("requeueing task %s as %s", slug, recovery_slug)
        db.update("tasks", {"id": f"eq.{result['task_id']}"}, {
            "state": "QUEUED",
            "note": f"branch missing, requeued by branch_repair_bot",
            "updated_at": "now()",
        })
        result["executed"] = True

    elif action == "merge_ready":
        _log.info("task %s branch is clean, flagging merge-ready", slug)
        db.update("tasks", {"id": f"eq.{result['task_id']}"}, {
            "note": "branch clean, merge-ready (branch_repair_bot)",
            "updated_at": "now()",
        })
        result["executed"] = True

    else:
        result["executed"] = False

    return result


def run(project_id=None):
    """Main entry: check and repair branches for DONE tasks."""
    if not ENABLED:
        _log.info("branch_repair_bot disabled")
        return []

    params = {"select": "id,slug,project_id,base_branch,kind,state",
              "state": "eq.DONE", "limit": str(BATCH_SIZE)}
    if project_id:
        params["project_id"] = f"eq.{project_id}"

    tasks = db.select("tasks", params) or []
    if not tasks:
        _log.info("no DONE tasks to check")
        return []

    results = []
    for t in tasks:
        pid = t.get("project_id", "")
        projects = db.select("projects", {"select": "repo_path", "id": f"eq.{pid}"}) or []
        if not projects:
            continue
        repo = db.localize_repo_path(projects[0].get("repo_path", ""))
        if not repo or not os.path.isdir(repo):
            continue

        result = check_task(t, repo)
        if result["action"] != "none":
            result = repair_task(t, repo, result)
            results.append(result)
            _log.info("task %s: %s -> %s (executed=%s)",
                      result["slug"], result["status"], result["action"],
                      result.get("executed", False))

    _log.info("branch_repair_bot: checked %d tasks, %d need action", len(tasks), len(results))
    return results


# --- Tests ---
def test_check_task_missing_branch():
    """Missing branch is detected."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["git", "init", td], capture_output=True)
        subprocess.run(["git", "-C", td, "commit", "--allow-empty", "-m", "init"], capture_output=True)
        task = {"id": "t1", "slug": "nonexistent-slug", "base_branch": "master", "kind": "build"}
        result = check_task(task, td)
        assert result["status"] == "missing", f"Expected missing, got {result}"
        assert result["action"] == "requeue"


def test_check_task_clean_branch():
    """Clean branch is detected."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["git", "init", td], capture_output=True)
        subprocess.run(["git", "-C", td, "commit", "--allow-empty", "-m", "init"],
                       capture_output=True, env={**os.environ, "GIT_AUTHOR_NAME": "test",
                       "GIT_COMMITTER_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
                       "GIT_COMMITTER_EMAIL": "t@t"})
        # Create branch off master
        subprocess.run(["git", "-C", td, "branch", "agent/test-slug"], capture_output=True)
        task = {"id": "t2", "slug": "test-slug", "base_branch": "master", "kind": "build"}
        result = check_task(task, td)
        assert result["status"] == "clean", f"Expected clean, got {result}"
        assert result["action"] == "merge_ready"


if __name__ == "__main__":
    test_check_task_missing_branch()
    test_check_task_clean_branch()
    print("All branch_repair_bot tests passed")
    results = run()
    print(f"Processed {len(results)} tasks")
