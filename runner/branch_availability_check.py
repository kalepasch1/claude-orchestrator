#!/usr/bin/env python3
"""
branch_availability_check.py - Pre-decomposition branch availability verification.

IMPROVEMENT (cost-efficiency, target 200x): Before queueing any task, check if its
base branch exists on the target machine (via git ls-remote or local cache).
Each missing branch cascades ~5 dependent tasks.

Integrates with planner.py and intake_watcher.py: call verify_base_branch()
before inserting a task into the queue.
"""
import os, sys, subprocess, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

CACHE_TTL = int(os.environ.get("ORCH_BRANCH_CACHE_TTL", "120"))
_lock = threading.Lock()
_cache = {}


def _cache_get(repo, branch):
    with _lock:
        entry = _cache.get((repo, branch))
        if entry and (time.time() - entry[1]) < CACHE_TTL:
            return entry[0]
    return None


def _cache_set(repo, branch, exists):
    with _lock:
        _cache[(repo, branch)] = (exists, time.time())


def branch_exists_local(repo, branch):
    if not repo or not os.path.isdir(repo):
        return None
    cached = _cache_get(repo, branch)
    if cached is not None:
        return cached
    try:
        r = subprocess.run(["git", "rev-parse", "--verify", branch],
                           cwd=repo, capture_output=True, timeout=10)
        exists = r.returncode == 0
        _cache_set(repo, branch, exists)
        return exists
    except Exception:
        return None


def branch_exists_remote(repo, branch):
    if not repo or not os.path.isdir(repo):
        return None
    cached = _cache_get(repo, f"remote:{branch}")
    if cached is not None:
        return cached
    try:
        r = subprocess.run(["git", "ls-remote", "--heads", "origin", branch],
                           cwd=repo, capture_output=True, text=True, timeout=15)
        exists = bool(r.stdout.strip())
        _cache_set(repo, f"remote:{branch}", exists)
        return exists
    except Exception:
        return None


def try_fetch_branch(repo, branch):
    if not repo or not os.path.isdir(repo):
        return False
    try:
        r = subprocess.run(["git", "fetch", "origin", f"{branch}:{branch}"],
                           cwd=repo, capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            _cache_set(repo, branch, True)
            return True
    except Exception:
        pass
    return False


def verify_base_branch(project, base_branch=None):
    """Verify a task's base branch is available before queueing.
    Returns (ok: bool, message: str)."""
    repo = db.localize_repo_path(project.get("repo_path", ""))
    base = base_branch or project.get("default_base") or "main"
    if not repo or not os.path.isdir(repo):
        return False, f"repo path not resolvable: {project.get('repo_path')}"
    if branch_exists_local(repo, base):
        return True, f"base branch '{base}' available locally"
    if try_fetch_branch(repo, base):
        return True, f"base branch '{base}' fetched from remote"
    remote = branch_exists_remote(repo, base)
    if remote:
        return False, f"base branch '{base}' exists on remote but fetch failed"
    return False, f"base branch '{base}' not found locally or on remote"


def verify_dep_branches(project, deps):
    """Verify all dependency branches exist. Returns (ok: bool, missing: list)."""
    if not deps:
        return True, []
    repo = db.localize_repo_path(project.get("repo_path", ""))
    missing = []
    for slug in deps:
        branch = f"agent/{slug}"
        if not branch_exists_local(repo, branch):
            tasks = db.select("tasks", {
                "select": "id,state", "slug": f"eq.{slug}",
                "project_id": f"eq.{project.get('id', '')}", "limit": "1",
            }) or []
            if tasks and tasks[0].get("state") in ("DONE", "MERGED"):
                continue
            missing.append(slug)
    return len(missing) == 0, missing


def audit_queued_tasks():
    """Audit all QUEUED tasks for branch availability issues."""
    projects = {p["id"]: p for p in (db.select("projects", {"select": "*"}) or [])}
    queued = db.select("tasks", {
        "select": "id,slug,project_id,base_branch,deps,state",
        "state": "eq.QUEUED", "limit": "500",
    }) or []
    issues = []
    for t in queued:
        proj = projects.get(t.get("project_id"), {})
        ok, msg = verify_base_branch(proj, t.get("base_branch"))
        if not ok:
            issues.append({"slug": t.get("slug"), "issue": "base_branch", "detail": msg})
        dep_ok, missing_deps = verify_dep_branches(proj, t.get("deps") or [])
        if not dep_ok:
            issues.append({"slug": t.get("slug"), "issue": "missing_deps",
                           "detail": f"missing dep branches: {missing_deps}"})
    print(f"branch_availability_check: audited {len(queued)} QUEUED, {len(issues)} issues")
    for i in issues:
        print(f"  [{i['issue']}] {i['slug']}: {i['detail']}")
    return issues


def invalidate(repo=None, branch=None):
    with _lock:
        if repo and branch:
            _cache.pop((repo, branch), None)
            _cache.pop((repo, f"remote:{branch}"), None)
        else:
            _cache.clear()


def stats():
    with _lock:
        now = time.time()
        total = len(_cache)
        stale = sum(1 for _, (_, ts) in _cache.items() if (now - ts) >= CACHE_TTL)
        return {"total": total, "stale": stale, "ttl": CACHE_TTL}


if __name__ == "__main__":
    audit_queued_tasks()
