#!/usr/bin/env python3
"""
branch_manager.py - Automated branch management and optimization.

Automatically detects and reports missing branches, re-requests them from
upstream if possible, or marks them for human intervention. Integrates with
missing_branch_audit.py diagnostic and adds active remediation.

Capabilities:
  - Detect missing agent branches for DONE tasks awaiting merge
  - Attempt automatic recovery via git fetch from origin
  - Requeue tasks whose branches are irrecoverably missing
  - Report unresolvable cases for operator attention
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_RECOVERY_ATTEMPTS = int(os.environ.get("ORCH_BRANCH_RECOVERY_CAP", "2"))
BATCH_SIZE = int(os.environ.get("ORCH_BRANCH_MANAGER_BATCH", "50"))


def _branch_exists(repo, branch):
    if not repo or not os.path.isdir(repo):
        return None
    try:
        r = subprocess.run(["git", "rev-parse", "--verify", branch],
                           cwd=repo, capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return None


def _fetch_branch(repo, branch):
    if not repo or not os.path.isdir(repo):
        return False
    try:
        r = subprocess.run(["git", "fetch", "origin", f"{branch}:{branch}"],
                           cwd=repo, capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def _ls_remote_branch(repo, branch):
    if not repo or not os.path.isdir(repo):
        return None
    try:
        r = subprocess.run(["git", "ls-remote", "--heads", "origin", branch],
                           cwd=repo, capture_output=True, text=True, timeout=15)
        return bool(r.stdout.strip())
    except Exception:
        return None


def _requeue_task(task, reason):
    retries = int(task.get("transient_retries") or 0)
    if retries >= MAX_RECOVERY_ATTEMPTS:
        db.update("tasks", {"id": task["id"]}, {
            "state": "BLOCKED",
            "note": f"branch_manager: branch missing after {retries} recovery attempts. "
                    f"Reason: {reason}. Needs manual intervention.",
            "updated_at": "now()",
        })
        return "BLOCKED"
    db.update("tasks", {"id": task["id"]}, {
        "state": "QUEUED",
        "transient_retries": retries + 1,
        "note": f"branch_manager: requeued — {reason} (attempt {retries+1}/{MAX_RECOVERY_ATTEMPTS})",
        "updated_at": "now()",
    })
    return "REQUEUED"


def detect_and_recover():
    """Scan DONE tasks for missing branches and attempt recovery."""
    projects = {p["id"]: p for p in (db.select("projects", {"select": "*"}) or [])}
    done_tasks = db.select("tasks", {
        "select": "id,slug,project_id,state,transient_retries,attempt,note",
        "state": "eq.DONE", "limit": str(BATCH_SIZE),
    }) or []

    recovered = requeued = blocked = skipped = 0
    for t in done_tasks:
        proj = projects.get(t.get("project_id"), {})
        repo = db.localize_repo_path(proj.get("repo_path", ""))
        branch = f"agent/{t.get('slug')}"
        if not repo or not os.path.isdir(repo):
            skipped += 1
            continue
        if _branch_exists(repo, branch):
            continue
        print(f"[branch_manager] missing: {branch}")
        if _fetch_branch(repo, branch):
            recovered += 1
            print(f"  -> recovered from remote")
            continue
        if _ls_remote_branch(repo, branch):
            print(f"  -> exists on remote but fetch failed, will retry")
            continue
        result = _requeue_task(t, "branch missing from local and remote")
        if result == "REQUEUED":
            requeued += 1
        else:
            blocked += 1
        print(f"  -> {result}")

    print(f"branch_manager: checked {len(done_tasks)} DONE tasks: "
          f"recovered={recovered}, requeued={requeued}, blocked={blocked}, skipped={skipped}")
    return {"recovered": recovered, "requeued": requeued, "blocked": blocked}


def run():
    try:
        import kill_switch
        if kill_switch.is_paused():
            print("branch_manager: paused"); return
    except Exception:
        pass
    return detect_and_recover()


if __name__ == "__main__":
    run()
