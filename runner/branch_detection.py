#!/usr/bin/env python3
"""
branch_detection.py — detect orphaned, missing, and diverged agent branches.

Provides utilities for automated branch recovery workflows:
  - detect_orphaned_branches: branches with no matching task
  - detect_missing_branches: tasks whose branches don't exist
  - detect_diverged_branches: branches that have diverged from base
  - classify_branch_state: single-branch health classifier

Used by branch_fleet_recovery and the merge train to identify
branches needing intervention before they block the pipeline.

Env vars:
    ORCH_BRANCH_DETECT_TIMEOUT   git command timeout in seconds (default 30)
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TIMEOUT = int(os.environ.get("ORCH_BRANCH_DETECT_TIMEOUT", "30"))


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
def _git(repo, *args):
    """Run a git command, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            ["git"] + list(args), cwd=repo,
            capture_output=True, text=True, timeout=TIMEOUT,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def _list_agent_branches(repo_path):
    """Return set of agent branch names (without 'agent/' prefix).

    Counts a branch as existing if it is present LOCALLY **or** on any remote.

    The remote half is the load-bearing part. Per the worktree convention in
    CLAUDE.md an agent pushes `agent/{slug}` and then the worktree is removed,
    and every other machine in the fleet only ever sees that branch as a
    remote-tracking ref. A local-only lookup therefore reports a branch that
    was pushed successfully as missing, and "missing" is what queues a
    recovery — so the blind spot does not merely under-report, it forks one
    piece of work into two branches and hands the merge train a conflict.

    Fail-soft: a git error yields whatever the other ref namespace produced,
    and an unreadable repo yields an empty set (same as before). An empty set
    means "could not tell", which callers must not read as "everything is
    missing" — see detect_missing_branches.
    """
    slugs = set()
    # Both ref namespaces in one pass. for-each-ref is used over `branch --list`
    # because it names the namespace explicitly rather than depending on the
    # porcelain's current-branch marker, and because it prints full refnames —
    # which is what lets a slug containing a slash survive intact below.
    rc, out, _ = _git(
        repo_path, "for-each-ref", "--format=%(refname)",
        "refs/heads/", "refs/remotes/",
    )
    if rc != 0 or not out:
        return slugs

    for ref in out.splitlines():
        ref = ref.strip()
        if ref.startswith("refs/heads/agent/"):
            slug = ref[len("refs/heads/agent/"):]
        elif ref.startswith("refs/remotes/"):
            # refs/remotes/<remote>/agent/<slug> — split off exactly the remote
            # name, so an unrelated branch like <remote>/feature/agent/x cannot
            # masquerade as agent/x.
            rest = ref[len("refs/remotes/"):]
            _, _, after_remote = rest.partition("/")
            if not after_remote.startswith("agent/"):
                continue
            slug = after_remote[len("agent/"):]
        else:
            continue
        # Slugs may contain slashes; only the `agent/` prefix is stripped, never
        # a trailing path component.
        if slug:
            slugs.add(slug)
    return slugs


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------
def detect_orphaned_branches(repo_path, known_slugs):
    """Find agent branches that have no matching task slug.

    Parameters
    ----------
    repo_path : str
        Path to the git repository.
    known_slugs : set | list
        Slugs of all known tasks (any state).

    Returns
    -------
    list[str]
        Slugs of orphaned branches.
    """
    if not repo_path or not os.path.isdir(repo_path):
        return []
    known = set(known_slugs) if known_slugs else set()
    branches = _list_agent_branches(repo_path)
    return sorted(b for b in branches if b not in known)


def detect_missing_branches(repo_path, tasks):
    """Find tasks whose expected agent branches don't exist.

    Parameters
    ----------
    repo_path : str
        Path to the git repository.
    tasks : list[dict]
        Task dicts with at least 'slug' and 'state' keys.

    Returns
    -------
    list[dict]
        Tasks that are in an active state but have no branch.
    """
    if not repo_path or not os.path.isdir(repo_path):
        return []
    active_states = {"QUEUED", "RUNNING", "BLOCKED", "IN_PROGRESS"}
    # REMOTE COUNTS. This used to list LOCAL branches only, which contradicts the fleet's
    # own lifecycle: CLAUDE.md states the worktree is removed after push while "the
    # agent/{slug} branch persists for merge-train pickup". A pushed branch whose local
    # ref was pruned therefore read as MISSING, and the fleet filed recover-missing-branch
    # tasks for work that was sitting on origin waiting to be merged. Recreating such a
    # branch forks one change into two and hands the merge train a conflict — the exact
    # failure the reconciliation contract warns about.
    # No include_remote flag any more: _list_agent_branches counts local AND
    # remote refs unconditionally now, because a branch that was pushed and had
    # its worktree removed exists only as a remote-tracking ref on every other
    # machine — and reporting it "missing" is what queues a duplicate recovery.
    branches = _list_agent_branches(repo_path)
    missing = []
    for task in (tasks or []):
        slug = task.get("slug", "")
        state = task.get("state", "")
        if state in active_states and slug and slug not in branches:
            missing.append(task)
    return missing


def detect_diverged_branches(repo_path, branches, base="master", threshold=100):
    """Find branches that have diverged more than *threshold* commits behind base.

    Returns list of dicts with 'branch', 'behind', 'ahead'.
    """
    if not repo_path or not os.path.isdir(repo_path):
        return []
    diverged = []
    for branch in (branches or []):
        full = f"agent/{branch}" if not branch.startswith("agent/") else branch
        rc, out, _ = _git(repo_path, "rev-list", "--left-right", "--count",
                          f"{base}...{full}")
        if rc != 0 or not out:
            continue
        parts = out.split()
        if len(parts) != 2:
            continue
        try:
            behind, ahead = int(parts[0]), int(parts[1])
        except (ValueError, TypeError):
            continue
        if behind > threshold:
            diverged.append({"branch": full, "behind": behind, "ahead": ahead})
    return diverged


def classify_branch_state(repo_path, slug, known_slugs=None, tasks=None):
    """Classify a single branch into one of: healthy, orphaned, missing, unknown.

    Returns a dict with 'slug', 'state', and 'detail'.
    """
    # Local OR remote, via the same helper the batch detectors use — a single
    # branch must not be classified "missing" on a rule the batch sweep would
    # have called healthy.
    branch_exists = slug in _list_agent_branches(repo_path)

    known = set(known_slugs) if known_slugs else set()
    task_slugs = {t.get("slug") for t in (tasks or [])}

    if branch_exists and slug in (known or task_slugs):
        return {"slug": slug, "state": "healthy", "detail": "branch and task both exist"}
    if branch_exists and slug not in (known or task_slugs):
        return {"slug": slug, "state": "orphaned", "detail": "branch exists but no task found"}
    if not branch_exists and slug in task_slugs:
        return {"slug": slug, "state": "missing", "detail": "task exists but branch is missing"}
    return {"slug": slug, "state": "unknown", "detail": "neither branch nor task found"}
