#!/usr/bin/env python3
"""
scm_branch_proposer.py — rule-based heuristic for proposing SCM branch operations.

Outputs proposed operations as plain dicts; never executes them. Callers (e.g. a
periodic job or task_state_change hook) decide whether and how to act on proposals.

Two rules are implemented:

  Creation: if a task is in QUEUED state and no agent/<slug> branch exists locally,
  propose {'action': 'create', 'project_id': ..., 'branch_name': 'agent/<slug>',
           'base': <base_branch>}.

  Deletion: if a task is in a terminal state (DONE or MERGED) and its agent/<slug>
  branch exists and its most-recent commit is older than ORCH_SCM_BRANCH_RETENTION_DAYS,
  propose {'action': 'delete', 'project_id': ..., 'branch_name': 'agent/<slug>',
           'reason': '...'}.

Configuration (all env vars):
  ORCH_SCM_BRANCH_HEURISTIC         enable/disable — default "true"
  ORCH_SCM_BRANCH_RETENTION_DAYS    days before a terminal branch is deletion-eligible — default 30
  ORCH_SCM_BRANCH_PREFIX            branch prefix — default "agent"
"""
import datetime
import os
import subprocess

HEURISTIC_ENABLED = os.environ.get("ORCH_SCM_BRANCH_HEURISTIC", "true").lower() in ("1", "true", "yes")
RETENTION_DAYS = int(os.environ.get("ORCH_SCM_BRANCH_RETENTION_DAYS", "30") or 30)
BRANCH_PREFIX = os.environ.get("ORCH_SCM_BRANCH_PREFIX", "agent")

CREATION_STATES = frozenset({"QUEUED"})
TERMINAL_STATES = frozenset({"DONE", "MERGED"})


def _git(repo, *args, timeout=30):
    try:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout)
    except Exception:
        class _R:
            returncode = 1; stdout = ""; stderr = ""
        return _R()


def _branch_exists(repo, branch):
    return bool(repo) and _git(repo, "rev-parse", "--verify", branch).returncode == 0


def _commit_age_days(repo, branch):
    """Return days since the most recent commit on branch, or None on error."""
    r = _git(repo, "log", "-1", "--format=%ct", branch)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        ts = int(r.stdout.strip())
    except ValueError:
        return None
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    then = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).replace(tzinfo=None)
    return max(0, (now - then).days)


def propose_branch_creation(tasks, project, repo=None):
    """Return creation proposals for QUEUED tasks whose agent branch does not exist.

    Args:
        tasks:   iterable of task dicts (id, slug, state, base_branch, project_id)
        project: project dict (id, repo_path, default_base)
        repo:    override repo path; falls back to project['repo_path']

    Returns list of dicts with keys: action, project_id, branch_name, base.
    """
    if not HEURISTIC_ENABLED:
        return []
    repo = repo or project.get("repo_path") or ""
    proposals = []
    for task in tasks:
        if task.get("state") not in CREATION_STATES:
            continue
        slug = task.get("slug") or ""
        if not slug:
            continue
        branch = f"{BRANCH_PREFIX}/{slug}"
        if _branch_exists(repo, branch):
            continue
        proposals.append({
            "action": "create",
            "project_id": project.get("id"),
            "branch_name": branch,
            "base": task.get("base_branch") or project.get("default_base") or "main",
        })
    return proposals


def propose_branch_deletion(tasks, project, repo=None, retention_days=None):
    """Return deletion proposals for terminal-state tasks with old agent branches.

    Args:
        tasks:          iterable of task dicts
        project:        project dict
        repo:           override repo path
        retention_days: override RETENTION_DAYS for this call

    Returns list of dicts with keys: action, project_id, branch_name, reason.
    """
    if not HEURISTIC_ENABLED:
        return []
    repo = repo or project.get("repo_path") or ""
    days = retention_days if retention_days is not None else RETENTION_DAYS
    proposals = []
    for task in tasks:
        if task.get("state") not in TERMINAL_STATES:
            continue
        slug = task.get("slug") or ""
        if not slug:
            continue
        branch = f"{BRANCH_PREFIX}/{slug}"
        if not _branch_exists(repo, branch):
            continue
        age = _commit_age_days(repo, branch)
        if age is None or age <= days:
            continue
        proposals.append({
            "action": "delete",
            "project_id": project.get("id"),
            "branch_name": branch,
            "reason": f"terminal state ({task['state']}), {age} days since last commit",
        })
    return proposals


def propose(tasks, project, repo=None, retention_days=None):
    """Run both creation and deletion rules; return the combined proposal list."""
    return (
        propose_branch_creation(tasks, project, repo=repo)
        + propose_branch_deletion(tasks, project, repo=repo, retention_days=retention_days)
    )
