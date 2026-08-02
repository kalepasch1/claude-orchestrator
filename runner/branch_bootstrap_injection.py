#!/usr/bin/env python3
"""
branch_bootstrap_injection.py - Enqueue-time branch bootstrap task injection.

When decomposition queues a task whose base branch is not staged on the machine
that will run it, the task is claimed, fails for lack of a checkout, and cascades
into its dependents. This module closes that gap at enqueue time: detect a
missing branch, and inject a small `branch_bootstrap` task (git fetch/clone +
rebase) AHEAD of the real task so the branch is materialized before the task is
ever claimable.

Ordering is enforced through the existing DAG, not a new schema column: the
bootstrap task's slug is appended to the real task's `deps`, and claim_task()
only claims dep-satisfied tasks. The bootstrap row also carries a numerically
low `priority` (lower = higher priority, see db.claim_task) so it is preferred
within its band. Machine routing rides the existing host-affinity mechanism —
the bootstrap task shares the real task's project (and therefore repo), so only
a machine holding that repo can claim it; the requesting machine is recorded in
the note for observability.

All entry points are fail-soft: bad input (None/missing path/permission errors)
returns a default instead of raising, and any injection failure leaves the
original task exactly as it would have been queued without this module.

Env vars:
    ORCH_BOOTSTRAP_INJECTION_ENABLED - "true" (default) / "false"
    ORCH_BOOTSTRAP_MAX_RETRIES       - fetch/clone retry budget (default 3)
    ORCH_BOOTSTRAP_TIMEOUT           - per-git-command timeout seconds (default 120)
"""
import os, sys, re, socket, subprocess, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import log as _log_mod

_log = _log_mod.get("branch_bootstrap_injection")

BOOTSTRAP_KIND = "branch_bootstrap"
BOOTSTRAP_PRIORITY = 1  # lower = higher priority (db.claim_task ordering)


def _enabled():
    return os.environ.get("ORCH_BOOTSTRAP_INJECTION_ENABLED", "true").lower() == "true"


def _max_retries():
    try:
        return int(os.environ.get("ORCH_BOOTSTRAP_MAX_RETRIES", "3"))
    except (TypeError, ValueError):
        return 3


def _timeout():
    try:
        return int(os.environ.get("ORCH_BOOTSTRAP_TIMEOUT", "120"))
    except (TypeError, ValueError):
        return 120


_lock = threading.Lock()
_stats = {
    "injected": 0,
    "skipped_pre_staged": 0,
    "skipped_duplicate": 0,
    "skipped_bad_input": 0,
    "skipped_disabled": 0,
    "errors": 0,
}


def _bump(key):
    with _lock:
        _stats[key] = _stats.get(key, 0) + 1


def stats():
    """Return a copy of injection counters for operators and tests."""
    with _lock:
        return dict(_stats)


def reset_stats():
    with _lock:
        for k in _stats:
            _stats[k] = 0


def _machine_id():
    try:
        return socket.gethostname() or "unknown"
    except Exception:
        return "unknown"


def _run_git(repo_path, args, timeout=15):
    try:
        proc = subprocess.run(["git"] + args, cwd=repo_path,
                              capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout or "").strip()
    except Exception:
        return -1, ""


def is_branch_pre_staged(repo_path, branch):
    """True if the branch is already available on this machine.

    Checks, in order: local ref, remote-tracking ref (refs/remotes/origin/<branch>),
    and any worktree currently holding the branch checked out. Fail-soft: returns
    False on None/missing path/permission errors — never raises.
    """
    try:
        if not repo_path or not branch or not os.path.isdir(repo_path):
            return False
        rc, _ = _run_git(repo_path, ["rev-parse", "--verify", "--quiet",
                                     f"refs/heads/{branch}"])
        if rc == 0:
            return True
        rc, _ = _run_git(repo_path, ["rev-parse", "--verify", "--quiet",
                                     f"refs/remotes/origin/{branch}"])
        if rc == 0:
            return True
        rc, out = _run_git(repo_path, ["worktree", "list", "--porcelain"])
        if rc == 0 and f"branch refs/heads/{branch}" in out:
            return True
        return False
    except Exception:
        return False


def bootstrap_slug(branch):
    """Deterministic slug for a branch's bootstrap task — the dedup key for the
    (repo, branch) pair (repo scoping comes from project_id on the row)."""
    safe = re.sub(r"[^a-z0-9\-]", "-", (branch or "unknown").lower())
    safe = re.sub(r"-+", "-", safe).strip("-")
    return f"branch-bootstrap-{safe}"[:60]


def make_bootstrap_task(current_task, repo_url, branch, machine_id=None):
    """Build the queue record that stages `branch` ahead of `current_task`.

    Returns a dict shaped like the rows the intake paths db.insert into "tasks",
    or None on bad input (no branch, or no project to attach to).
    """
    try:
        current_task = current_task or {}
        if not branch or not current_task.get("project_id"):
            return None
        machine = machine_id or _machine_id()
        retries, timeout = _max_retries(), _timeout()
        prompt = (
            f"BRANCH BOOTSTRAP: stage branch '{branch}' for repo {repo_url or '(project repo)'} "
            f"on this machine before dependent tasks run.\n"
            f"Steps (each git command capped at {timeout}s):\n"
            f"1. If the repo checkout is missing, `git clone {repo_url or '<project repo_url>'}` first.\n"
            f"2. `git fetch origin {branch}:{branch}` (or `git fetch origin {branch}` if the local "
            f"branch is currently checked out, then `git rebase origin/{branch}`).\n"
            f"3. Verify with `git rev-parse --verify {branch}`.\n"
            f"On network failure retry up to {retries} times with exponential backoff. "
            f"Fail-soft: if all retries fail, exit non-zero so the runner's normal retry path "
            f"picks the task back up — do not wedge or loop forever."
        )
        record = {
            "project_id": current_task.get("project_id"),
            "slug": bootstrap_slug(branch),
            "prompt": prompt,
            "kind": BOOTSTRAP_KIND,
            "state": "QUEUED",
            "priority": BOOTSTRAP_PRIORITY,
            "note": f"branch-bootstrap {branch} requested-by={current_task.get('slug', '?')} "
                    f"machine={machine}",
        }
        if current_task.get("id"):
            record["parent_task_id"] = current_task["id"]
        return record
    except Exception:
        return None


def _existing_bootstrap(project_id, slug):
    """Is a bootstrap task for this (project, branch) already queued or in-flight?

    Returns True/False, or None when the DB check itself failed (callers treat
    None as "don't inject" so a flaky DB can't flood the queue with duplicates).
    """
    try:
        rows = db.select("tasks", {"select": "id,state",
                                   "project_id": f"eq.{project_id}",
                                   "slug": f"eq.{slug}",
                                   "state": "in.(QUEUED,RUNNING,RETRY)",
                                   "limit": "1"})
        if rows is None:
            return None
        return len(rows) > 0
    except Exception:
        return None


def _add_dep(task_row, dep_slug):
    deps = task_row.get("deps") or []
    if dep_slug not in deps:
        task_row["deps"] = list(deps) + [dep_slug]


def inject_bootstrap_if_needed(task_row, project, machine_id=None):
    """Called at enqueue time, before the real task row is inserted.

    If the task's base branch is not pre-staged locally, insert (or reuse) a
    `branch_bootstrap` task and append its slug to task_row['deps'] so the real
    task cannot be claimed until the branch exists. Mutates task_row in place.

    Returns {"injected": bool, "reason": str, "bootstrap_slug": str|None} and
    never raises — any failure leaves task_row queueable as-is.
    """
    result = {"injected": False, "reason": "", "bootstrap_slug": None}
    try:
        if not _enabled():
            _bump("skipped_disabled")
            result["reason"] = "disabled"
            return result
        if not isinstance(task_row, dict) or not isinstance(project, dict):
            _bump("skipped_bad_input")
            result["reason"] = "bad-input"
            return result
        branch = task_row.get("base_branch") or project.get("default_base") or "main"
        try:
            repo_path = db.localize_repo_path(project.get("repo_path") or "")
        except Exception:
            repo_path = None
        if not repo_path or not os.path.isdir(repo_path):
            _bump("skipped_bad_input")
            result["reason"] = "missing-repo-path"
            return result
        if is_branch_pre_staged(repo_path, branch):
            _bump("skipped_pre_staged")
            result["reason"] = "pre-staged"
            return result

        slug = bootstrap_slug(branch)
        existing = _existing_bootstrap(task_row.get("project_id"), slug)
        if existing is None:
            _bump("errors")
            result["reason"] = "db-error"
            return result
        if existing:
            # A bootstrap for this (repo, branch) is already queued or in-flight:
            # don't duplicate it, just order this task behind it.
            _add_dep(task_row, slug)
            _bump("skipped_duplicate")
            result.update(reason="duplicate", bootstrap_slug=slug)
            return result

        record = make_bootstrap_task(task_row,
                                     project.get("repo_url") or project.get("repo_path"),
                                     branch, machine_id=machine_id)
        if not record:
            _bump("skipped_bad_input")
            result["reason"] = "bad-input"
            return result
        inserted = None
        try:
            inserted = db.insert("tasks", record)
        except Exception:
            inserted = None
        if not inserted:
            # Never dep on a row that didn't land — the task would wait forever.
            _bump("errors")
            result["reason"] = "insert-failed"
            return result
        _add_dep(task_row, slug)
        _bump("injected")
        _log.info("injected %s ahead of %s (branch %s)", slug,
                  task_row.get("slug", "?"), branch)
        result.update(injected=True, reason="injected", bootstrap_slug=slug)
        return result
    except Exception as e:
        _bump("errors")
        result["reason"] = f"error:{e.__class__.__name__}"
        return result
