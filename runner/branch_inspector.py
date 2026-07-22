#!/usr/bin/env python3
"""
branch_inspector.py - inspect local branches to infer task state transitions.

When a task is in RUNNING/QUEUED but its agent/<slug> branch already has commits,
the task may have actually completed (or partially completed) on another runner.
This module inspects local branches and returns structured information that the
state-transition logic (runner.py, merge_train.py, queue_janitor.py) can use to
auto-recover tasks stuck in limbo.

Fail-soft: returns empty results on any error, never raises.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def _git(repo, *args, timeout=15):
    """Run a git command, return (stdout, ok)."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo,
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode == 0
    except Exception:
        return "", False

def branch_exists(repo, branch):
    """Check if a branch exists in the given repo. Returns None if repo is invalid."""
    if not repo or not os.path.isdir(repo):
        return None
    _, ok = _git(repo, "rev-parse", "--verify", branch)
    return ok


def branch_commit_count(repo, branch, base="master"):
    """Count commits on branch ahead of base. Returns 0 on error."""
    if not repo or not os.path.isdir(repo):
        return 0
    out, ok = _git(repo, "rev-list", "--count", f"{base}..{branch}")
    if not ok:
        return 0
    try:
        return int(out)
    except ValueError:
        return 0


def branch_last_commit_msg(repo, branch):
    """Get the last commit message on a branch. Returns empty string on error."""
    if not repo or not os.path.isdir(repo):
        return ""
    out, ok = _git(repo, "log", "-1", "--format=%s", branch)
    return out if ok else ""

def branch_last_commit_time(repo, branch):
    """Get ISO timestamp of last commit on branch. Returns empty string on error."""
    if not repo or not os.path.isdir(repo):
        return ""
    out, ok = _git(repo, "log", "-1", "--format=%aI", branch)
    return out if ok else ""


def inspect_task_branch(task, repo=None):
    """Inspect the local branch for a task and return structured info."""
    slug = task.get("slug", "")
    branch = f"agent/{slug}"
    state = task.get("state", "")

    if not repo:
        proj = db.select("projects", {"select": "repo_path", "id": f"eq.{task.get('project_id')}"})
        raw = (proj[0].get("repo_path", "") if proj else "")
        repo = db.localize_repo_path(raw)

    exists = branch_exists(repo, branch)
    if exists is None:
        return {"exists": None, "commits_ahead": 0, "last_message": "",
                "last_time": "", "has_work": False, "suggested_state": None}
    if not exists:
        return {"exists": False, "commits_ahead": 0, "last_message": "",
                "last_time": "", "has_work": False, "suggested_state": None}

    commits = branch_commit_count(repo, branch)
    msg = branch_last_commit_msg(repo, branch)    ts = branch_last_commit_time(repo, branch)
    has_work = commits > 0

    suggested = None
    if state == "RUNNING" and has_work:
        suggested = "DONE"
    elif state == "QUEUED" and has_work:
        suggested = "DONE"

    return {
        "exists": True,
        "commits_ahead": commits,
        "last_message": msg,
        "last_time": ts,
        "has_work": has_work,
        "suggested_state": suggested,
    }


def inspect_all_running(project_id=None):
    """Inspect branches for all RUNNING tasks, return list with branch info."""
    filters = {"select": "id,slug,project_id,state,account,updated_at",
               "state": "eq.RUNNING", "limit": "200"}
    if project_id:
        filters["project_id"] = f"eq.{project_id}"
    tasks = db.select("tasks", filters) or []
    if not tasks:
        return []
    proj_cache = {}
    results = []    for t in tasks:
        pid = t.get("project_id")
        if pid not in proj_cache:
            proj = db.select("projects", {"select": "repo_path", "id": f"eq.{pid}"})
            raw = (proj[0].get("repo_path", "") if proj else "")
            proj_cache[pid] = db.localize_repo_path(raw)
        info = inspect_task_branch(t, repo=proj_cache[pid])
        if info.get("has_work") or info.get("exists"):
            results.append({**t, "branch_info": info})
    return results


def auto_recover_stuck(project_id=None, dry_run=True):
    """Find RUNNING tasks with completed branch work and optionally transition them."""
    stuck = inspect_all_running(project_id)
    recovered = []
    for item in stuck:
        info = item.get("branch_info", {})
        if not info.get("has_work") or not info.get("suggested_state"):
            continue
        task_id = item["id"]
        new_state = info["suggested_state"]
        if not dry_run:
            try:
                db.update("tasks", {"id": task_id}, {
                    "state": new_state,
                    "note": (f"branch_inspector: auto-recovered from RUNNING -> {new_state}, "
                             f"{info['commits_ahead']} commits found, "
                             f"last: {info['last_message'][:80]}"),
                })            except Exception:
                continue
        recovered.append({
            "id": task_id,
            "slug": item.get("slug"),
            "from_state": "RUNNING",
            "to_state": new_state,
            "commits": info["commits_ahead"],
            "last_commit": info["last_message"],
            "dry_run": dry_run,
        })
    return recovered


if __name__ == "__main__":
    import json
    mode = sys.argv[1] if len(sys.argv) > 1 else "inspect"
    pid = sys.argv[2] if len(sys.argv) > 2 else None
    if mode == "recover":
        results = auto_recover_stuck(pid, dry_run="--apply" not in sys.argv)
    else:
        results = inspect_all_running(pid)
    print(json.dumps(results, indent=2, default=str))