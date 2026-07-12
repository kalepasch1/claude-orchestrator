#!/usr/bin/env python3
"""claim_affinity.py - soft affinity for multi-machine task claiming.

Slice-3: when a fallback machine claims a task from a non-local project,
immediately bootstrap the branch by pre-fetching in parallel so execution
can start without waiting for a full clone.
"""
import os, socket, subprocess, sys, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HOST = socket.gethostname()

# Track bootstrap state to avoid duplicate fetches
_bootstrap_lock = threading.Lock()
_bootstrapping = set()  # project_ids currently being bootstrapped


def soft_affinity_sort(queued, local_repo_pids):
    """Sort tasks: local-project tasks first, remote tasks second."""
    if local_repo_pids is None:
        return queued
    if os.environ.get("ORCH_SOFT_AFFINITY", "true").lower() not in ("true", "1", "yes"):
        return queued
    local = [t for t in queued if t.get("project_id") in local_repo_pids]
    remote = [t for t in queued if t.get("project_id") not in local_repo_pids]
    if local:
        return local + remote
    if remote and os.environ.get("ORCH_SOFT_AFFINITY_FALLTHROUGH", "true").lower() in ("true", "1", "yes"):
        print(f"[claim_affinity] no local tasks on {HOST}, falling through to {len(remote)} remote tasks", flush=True)
        # Slice-3: trigger parallel branch bootstrap for remote projects
        _trigger_bootstrap(remote, local_repo_pids)
        return remote
    return []


def affinity_score(task, local_repo_pids):
    """0 = local (preferred), 1 = remote."""
    if local_repo_pids is None:
        return 0
    return 0 if task.get("project_id") in local_repo_pids else 1


# ── Slice-3: parallel branch bootstrapping ───────────────────────────────────

def _find_repo_path(project_id):
    """Look up the repo_path for a project from the DB."""
    try:
        import db
        rows = db.select("projects", {"select": "repo_path", "id": f"eq.{project_id}", "limit": "1"})
        if rows and rows[0].get("repo_path"):
            return rows[0]["repo_path"]
    except Exception:
        pass
    return None


def _do_bootstrap(project_id, base_branch):
    """Fetch the base branch so the worktree can be created immediately."""
    repo = _find_repo_path(project_id)
    if not repo or not os.path.isdir(repo):
        return
    with _bootstrap_lock:
        if project_id in _bootstrapping:
            return
        _bootstrapping.add(project_id)
    try:
        # Fetch only the needed branch, shallow if possible
        subprocess.run(
            ["git", "fetch", "origin", base_branch or "master", "--depth=1"],
            cwd=repo, capture_output=True, text=True, timeout=60
        )
        print(f"[claim_affinity] bootstrapped {base_branch or 'master'} for project {project_id[:8]} on {HOST}", flush=True)
    except Exception as e:
        print(f"[claim_affinity] bootstrap failed for {project_id[:8]}: {e}", flush=True)
    finally:
        with _bootstrap_lock:
            _bootstrapping.discard(project_id)


def _trigger_bootstrap(remote_tasks, local_repo_pids):
    """Kick off parallel git fetches for remote projects we're about to claim from."""
    if os.environ.get("ORCH_BOOTSTRAP_ON_FALLBACK", "true").lower() not in ("true", "1", "yes"):
        return
    seen = set()
    for t in remote_tasks:
        pid = t.get("project_id")
        if not pid or pid in seen or pid in (local_repo_pids or set()):
            continue
        seen.add(pid)
        base = t.get("base_branch") or "master"
        th = threading.Thread(target=_do_bootstrap, args=(pid, base), daemon=True)
        th.start()


def bootstrap_for_task(task):
    """Explicitly bootstrap a single task's branch. Called by the runner
    right after claiming a remote task, before setting up the worktree."""
    pid = task.get("project_id")
    if not pid:
        return
    base = task.get("base_branch") or "master"
    _do_bootstrap(pid, base)
