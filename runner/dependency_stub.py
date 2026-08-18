#!/usr/bin/env python3
"""
dependency_stub.py - synthesize thin dependency stubs for missing upstream branches.

When a task depends on an upstream branch (agent/<dep-slug>) that doesn't exist yet
(the upstream task is still QUEUED/RUNNING, or its branch was lost), the merge pipeline
hard-stalls: the dependent task can't rebase, test, or merge. This module breaks that
wall by synthesizing a minimal stub branch from the best available source:

  1. The base branch itself (identity stub) — the dependent task was already built
     against this base, so a stub that IS the base lets integration proceed immediately.
  2. A previous version of the dep branch (from reflog or remote) — partial work is
     better than nothing for unblocking downstream.
  3. A patch template match — if patch_templates has a cached diff for a similar slug,
     apply it to the base to approximate the dep's intended changes.

The stub is clearly marked (commit message, branch description) so the train knows to
re-integrate when the real branch lands. Stubs are temporary scaffolding, not permanent
merges.

Thread-safe, fail-soft. Env: ORCH_DEP_STUB_ENABLED (default "true").
"""
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ENABLED = os.environ.get("ORCH_DEP_STUB_ENABLED", "true").lower() in ("true", "1", "yes")
_STUB_TTL_S = int(os.environ.get("ORCH_DEP_STUB_TTL", "3600"))  # stubs expire after 1h
_STUB_PREFIX = "stub/"
_STUB_MARKER = "[dependency-stub]"

try:
    import db
except ImportError:
    db = None

try:
    import patch_templates
except ImportError:
    patch_templates = None


def _git(repo, *args, timeout=60):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout)


def _branch_exists(repo, branch):
    return _git(repo, "rev-parse", "--verify", branch).returncode == 0


def _stub_branch_name(dep_slug):
    """Stub branches live in a separate namespace to avoid collisions."""
    return f"{_STUB_PREFIX}{dep_slug}"


def _try_reflog_recovery(repo, branch):
    """Check if the branch existed recently and can be recovered from reflog."""
    try:
        r = _git(repo, "reflog", "show", branch, "--no-walk", timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            # The branch existed at some point — recover its last known state
            commit = r.stdout.strip().split()[0]
            if commit and _git(repo, "rev-parse", "--verify", commit).returncode == 0:
                return commit
    except Exception:
        pass
    return None


def _try_remote_recovery(repo, branch):
    """Try fetching the branch from origin."""
    try:
        _git(repo, "fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}", timeout=120)
        r = _git(repo, "rev-parse", "--verify", f"refs/remotes/origin/{branch}")
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _try_patch_template(repo, dep_slug, base):
    """Look for a cached patch template matching this slug and apply it."""
    if not patch_templates:
        return None
    try:
        # patch_templates.find_template returns a diff string if a match exists
        if hasattr(patch_templates, "find_template"):
            template = patch_templates.find_template(dep_slug)
            if template and template.get("diff"):
                # Apply the patch in a detached HEAD from base
                _git(repo, "checkout", "--detach", base)
                r = subprocess.run(
                    ["git", "apply", "--3way", "--allow-empty", "-"],
                    input=template["diff"], cwd=repo,
                    capture_output=True, text=True, timeout=30,
                )
                if r.returncode == 0:
                    _git(repo, "add", "-A")
                    _git(repo, "commit", "--allow-empty", "-m",
                         f"{_STUB_MARKER} stub from patch template for {dep_slug}")
                    result = _git(repo, "rev-parse", "HEAD")
                    return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        pass
    finally:
        try:
            _git(repo, "checkout", "-", timeout=15)
        except Exception:
            pass
    return None


def synthesize_stub(repo, dep_slug, base):
    """Synthesize a stub branch for a missing dependency.

    Tries recovery sources in priority order:
      1. Remote origin (real branch, just not fetched)
      2. Reflog (branch existed locally, was deleted)
      3. Patch template (approximate the dep's changes)
      4. Identity stub (base branch as-is — unblocks immediately)

    Returns {"stub_branch": str, "source": str, "commit": str} on success,
    or None if disabled or repo is invalid.
    """
    if not _ENABLED:
        return None
    if not repo or not os.path.isdir(repo):
        return None

    agent_branch = f"agent/{dep_slug}"
    stub_branch = _stub_branch_name(dep_slug)

    # If the real branch already exists, no stub needed
    if _branch_exists(repo, agent_branch):
        return None

    # If a stub already exists and is fresh, reuse it
    if _branch_exists(repo, stub_branch):
        age = _stub_age(repo, stub_branch)
        if age is not None and age < _STUB_TTL_S:
            commit = _git(repo, "rev-parse", stub_branch).stdout.strip()
            return {"stub_branch": stub_branch, "source": "cached", "commit": commit}
        # Stale stub — remove and re-synthesize
        _git(repo, "branch", "-D", stub_branch)

    # Source 1: remote
    commit = _try_remote_recovery(repo, agent_branch)
    if commit:
        _git(repo, "branch", stub_branch, commit)
        _mark_stub(repo, stub_branch, "remote-recovery")
        return {"stub_branch": stub_branch, "source": "remote", "commit": commit}

    # Source 2: reflog
    commit = _try_reflog_recovery(repo, agent_branch)
    if commit:
        _git(repo, "branch", stub_branch, commit)
        _mark_stub(repo, stub_branch, "reflog-recovery")
        return {"stub_branch": stub_branch, "source": "reflog", "commit": commit}

    # Source 3: patch template
    commit = _try_patch_template(repo, dep_slug, base)
    if commit:
        _git(repo, "branch", stub_branch, commit)
        _mark_stub(repo, stub_branch, "patch-template")
        return {"stub_branch": stub_branch, "source": "patch-template", "commit": commit}

    # Source 4: identity stub (base as-is)
    base_commit = _git(repo, "rev-parse", base).stdout.strip()
    if base_commit and _git(repo, "branch", stub_branch, base_commit).returncode == 0:
        _mark_stub(repo, stub_branch, "identity")
        return {"stub_branch": stub_branch, "source": "identity", "commit": base_commit}

    return None


def _mark_stub(repo, branch, source):
    """Tag the stub branch with metadata so the train knows it's synthetic."""
    try:
        _git(repo, "config", f"branch.{branch}.description",
             f"{_STUB_MARKER} source={source} created={int(time.time())}")
    except Exception:
        pass


def _stub_age(repo, branch):
    """Return age in seconds of a stub branch, or None if not a stub."""
    try:
        r = _git(repo, "config", f"branch.{branch}.description")
        if r.returncode == 0 and _STUB_MARKER in r.stdout:
            m = re.search(r"created=(\d+)", r.stdout)
            if m:
                return int(time.time()) - int(m.group(1))
    except Exception:
        pass
    return None


def is_stub(repo, branch):
    """Check if a branch is a dependency stub."""
    try:
        r = _git(repo, "config", f"branch.{branch}.description")
        return r.returncode == 0 and _STUB_MARKER in r.stdout
    except Exception:
        return False


def cleanup_stubs(repo, project_id=None):
    """Remove stale or superseded stubs.

    A stub is superseded when its real agent/ branch now exists.
    A stub is stale when it exceeds ORCH_DEP_STUB_TTL.
    """
    removed = []
    try:
        r = _git(repo, "branch", "--list", f"{_STUB_PREFIX}*")
        if r.returncode != 0:
            return removed
        for line in r.stdout.strip().splitlines():
            branch = line.strip().lstrip("* ")
            if not branch.startswith(_STUB_PREFIX):
                continue
            dep_slug = branch[len(_STUB_PREFIX):]
            agent_branch = f"agent/{dep_slug}"
            # Superseded: real branch exists
            if _branch_exists(repo, agent_branch):
                _git(repo, "branch", "-D", branch)
                removed.append((branch, "superseded"))
                continue
            # Stale: older than TTL
            age = _stub_age(repo, branch)
            if age is not None and age > _STUB_TTL_S:
                _git(repo, "branch", "-D", branch)
                removed.append((branch, "stale"))
    except Exception:
        pass
    return removed


def resolve_deps_with_stubs(repo, task, base):
    """For a task with deps, ensure each dep's branch exists — synthesizing stubs as needed.

    Returns {"resolved": [...], "failed": [...], "stubs_created": [...]}.
    Called by the merge train before integration to unblock tasks whose deps'
    branches are missing.
    """
    deps = task.get("deps") or []
    if not deps:
        return {"resolved": [], "failed": [], "stubs_created": []}

    resolved = []
    failed = []
    stubs_created = []

    for dep_slug in deps:
        agent_branch = f"agent/{dep_slug}"
        if _branch_exists(repo, agent_branch):
            resolved.append(dep_slug)
            continue
        stub = synthesize_stub(repo, dep_slug, base)
        if stub:
            stubs_created.append({"dep": dep_slug, **stub})
            resolved.append(dep_slug)
        else:
            failed.append(dep_slug)

    return {"resolved": resolved, "failed": failed, "stubs_created": stubs_created}


def stats():
    """Return stub statistics for observability."""
    return {
        "enabled": _ENABLED,
        "ttl_s": _STUB_TTL_S,
    }
