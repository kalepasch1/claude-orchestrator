#!/usr/bin/env python3
"""base_branch — resolve a project's real default branch instead of guessing "main".

WHY THIS EXISTS
---------------
Four places in the runner end a fallback chain with a bare ``or "main"``:

    agent_market.py:562        project.get("default_branch") or ... or "main"
    approval_merge.py:436      t.get("base_branch") or proj.get("default_base", "main")
    auto_conflict_resolver.py  proj.get("base_branch") or ... or "main"
    auto_remediate.py:569      task.get("base_branch") or "main"

Beethoven's default branch is ``master``. So is racefeed's, hisanta's, and
apparently's. The guess is wrong for most of the fleet, and two of those chains
compound it by reading a key the projects table does not have — the column is
``default_base``, not ``default_branch`` — so they never had a chance to read the
right value and fell through to the literal every single time.

MEASURED 2026-08-24: five consecutive beethoven tasks were claimed carrying
``base_branch='main'`` while the same rows carried ``default_base='master'``.
Every one of them failed its first worktree command with
``fatal: invalid reference: origin/main`` and only survived on a shell ``||``
fallback. A task whose recorded base branch does not exist cannot be branched,
rebased, or merged without that fallback, and nothing upstream ever noticed
because the literal is syntactically fine.

Resolution order, most authoritative first:

  1. an explicit, non-empty ``base_branch`` on the task itself
  2. the project row's ``default_base`` / ``default_branch`` / ``prod_branch``
  3. what the repository actually says: ``origin/HEAD``, then a probe for the
     conventional names
  4. ``DEFAULT_FALLBACK`` — still a guess, but now the last resort rather than
     the first answer

Fail-soft by repo convention: every public function returns a usable branch name
or a sensible default and never raises, so a caller in the claim path cannot be
wedged by a missing repo, a detached HEAD, or a git binary that hangs.

Config:
    ORCH_DEFAULT_BASE_BRANCH   final fallback            (default "main")
    ORCH_BASE_BRANCH_TIMEOUT   per-git-call seconds      (default 10)
"""

from __future__ import annotations

import os
import subprocess

#: Names to probe on the remote, in order, when origin/HEAD is not set. Ordered by
#: how many repos in this fleet actually use them, not by fashion.
CANDIDATE_BRANCHES = ("master", "main", "dev", "trunk")

#: Project-row keys that may carry the default branch. `default_base` is the real
#: column; the other two are read because existing call sites ask for them.
PROJECT_KEYS = ("default_base", "default_branch", "prod_branch")

DEFAULT_FALLBACK = "main"
DEFAULT_TIMEOUT = 10


def _fallback() -> str:
    return os.environ.get("ORCH_DEFAULT_BASE_BRANCH", "").strip() or DEFAULT_FALLBACK


def _timeout() -> int:
    raw = os.environ.get("ORCH_BASE_BRANCH_TIMEOUT", "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    return value if 1 <= value <= 300 else DEFAULT_TIMEOUT


def _clean(value) -> str:
    """A branch name only counts if it is a non-empty string."""
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _is_repo(repo) -> bool:
    """True only for a path-like value that names a real directory."""
    if not isinstance(repo, (str, bytes, os.PathLike)) or not repo:
        return False
    try:
        return os.path.isdir(repo)
    except (TypeError, ValueError, OSError):
        return False


def _git(args, repo):
    """Run git with a bounded timeout. Returns ``None`` on any failure."""
    if not _is_repo(repo):
        return None
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=_timeout(),
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def from_project(project) -> str:
    """First usable branch name on a project row, or ``""``."""
    if not isinstance(project, dict):
        return ""
    for key in PROJECT_KEYS:
        name = _clean(project.get(key))
        if name:
            return name
    return ""


def remote_head(repo) -> str:
    """The branch ``origin/HEAD`` points at, or ``""`` if it is unset."""
    r = _git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], repo)
    if r is None or r.returncode != 0:
        return ""
    ref = _clean(r.stdout)
    prefix = "refs/remotes/origin/"
    return ref[len(prefix):] if ref.startswith(prefix) else ""


def ref_exists(repo, branch) -> bool:
    """True if ``origin/<branch>`` is a real ref in ``repo``."""
    name = _clean(branch)
    if not name:
        return False
    r = _git(["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{name}"], repo)
    return bool(r is not None and r.returncode == 0 and _clean(r.stdout))


def from_repo(repo) -> str:
    """Ask the repository itself: origin/HEAD first, then probe the usual names."""
    head = remote_head(repo)
    if head:
        return head
    for name in CANDIDATE_BRANCHES:
        if ref_exists(repo, name):
            return name
    return ""


def resolve(task=None, project=None, repo=None) -> str:
    """Best available base branch. Never empty, never raises.

    Consults, in order: the task's own ``base_branch``, the project row, the
    repository on disk, then the configured fallback.
    """
    if isinstance(task, dict):
        name = _clean(task.get("base_branch"))
        if name:
            return name
    name = from_project(project)
    if name:
        return name
    name = from_repo(repo)
    if name:
        return name
    return _fallback()


def resolve_verified(task=None, project=None, repo=None) -> str:
    """Like :func:`resolve`, but discard a recorded name the repo does not have.

    This is the one that would have caught the 2026-08-24 case: a task row said
    ``main``, the repo had no ``origin/main``, and the recorded value was used
    anyway. When ``repo`` is unreadable there is nothing to verify against, so
    this degrades to :func:`resolve` rather than inventing an answer.
    """
    candidate = resolve(task=task, project=project, repo=repo)
    if not _is_repo(repo):
        return candidate
    if ref_exists(repo, candidate):
        return candidate
    actual = from_repo(repo)
    return actual or candidate


def mismatch(task=None, project=None, repo=None):
    """``(recorded, actual)`` when a recorded branch is absent from the repo.

    Returns ``None`` when there is no disagreement or nothing to compare — so a
    caller can log or file exactly the drift that silently broke five tasks.
    """
    recorded = resolve(task=task, project=project, repo=repo)
    if not _is_repo(repo) or ref_exists(repo, recorded):
        return None
    actual = from_repo(repo)
    return (recorded, actual) if actual and actual != recorded else None
