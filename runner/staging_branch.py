"""Which branch a project integrates on, resolved in one place.

THE PROBLEM THIS CLOSES. Six modules read ``ORCH_STAGING_BRANCH`` straight from
the environment with the fleet default ``orchestrator/dev`` -- the push guard,
approval_merge, merge_truth, the integration sweeper, merge_reconciliation and
improvement_verify -- while the ``projects`` registry has carried a per-project
``staging_branch`` column all along that only merge_truth consulted, and only as
a fallback behind the environment. So the staging branch was fleet-wide in
practice: one process variable for sixteen repos.

Measured 2026-09-10: in ``smarter``, ``origin/orchestrator/dev`` was 84 commits
behind ``main`` and every change actually integrated on ``origin/dev`` (35 ahead
of main, 119 ahead of orchestrator/dev); in ``apparently-law`` the same shape,
78 and 39. Macey decided that day that those two projects integrate on ``dev``.
Flipping the environment variable would have moved all sixteen projects at once,
and for any repo with no ``dev`` on its remote the push guard would have stopped
applying at all ("no such branch -- staging rule does not apply"), which is a
gate quietly switching itself off. Per project is the only honest shape.

PRECEDENCE, and why it is this way round:

    projects.staging_branch  (explicit, per project)
      > ORCH_STAGING_BRANCH  (the fleet's process configuration)
        > "orchestrator/dev"  (the fleet default)

A value somebody wrote against one project is more specific than one written
for the process, so it wins. merge_truth used to put the environment first
because "older rows can lag the process configuration"; today every row holds
the default, so nothing changes for a project nobody has configured, and a
project somebody HAS configured is no longer overridden by a variable that was
never about it.

FAILS TOWARD THE DEFAULT, LOUDLY. If the registry cannot be read -- no
credentials on a laptop, PostgREST down, an unknown repo path -- the answer is
the environment or the fleet default, and ``source`` says which, so a log line
can show "orchestrator/dev (fleet default; registry unreachable)" rather than
pretending the registry agreed.
"""
from __future__ import annotations

import os

FLEET_DEFAULT = "orchestrator/dev"
ENV_VAR = "ORCH_STAGING_BRANCH"

SOURCE_REGISTRY = "project registry"
SOURCE_ENV = ENV_VAR
SOURCE_DEFAULT = "fleet default"


def fleet_staging_branch():
    """The process-wide answer: the environment variable, else the fleet default."""
    value = os.environ.get(ENV_VAR, "")
    return (value.strip(), SOURCE_ENV) if value and value.strip() else (FLEET_DEFAULT, SOURCE_DEFAULT)


def _normalise_repo(repo):
    if not repo:
        return None
    try:
        return os.path.realpath(str(repo)).rstrip("/")
    except (TypeError, ValueError):
        return None


def project_row_for_repo(repo, select=None):
    """The ``projects`` row whose ``repo_path`` is this repo, or None.

    ``select`` is injectable so a test never needs a database. Any failure --
    missing credentials, network, a row that is not a dict -- is None: the
    caller falls back and says so.
    """
    path = _normalise_repo(repo)
    if not path:
        return None
    if select is None:
        try:
            import db  # noqa: WPS433 -- runner modules import siblings by bare name
            select = db.select
        except Exception:
            return None
    try:
        rows = select("projects", {
            "select": "id,name,repo_path,staging_branch,prod_branch,default_base",
            "repo_path": f"eq.{path}",
        }) or []
    except Exception:
        return None
    row = rows[0] if rows else None
    return row if isinstance(row, dict) else None


def staging_branch_for(repo=None, row=None, select=None):
    """(branch, source) for a project.

    ``row`` is a ``projects`` row when the caller already has one (approval_merge
    and merge_truth do); otherwise ``repo`` is looked up by path. A blank
    ``staging_branch`` on the row is treated as unset, not as a branch called
    "".
    """
    if row is None and repo is not None:
        row = project_row_for_repo(repo, select=select)
    value = row.get("staging_branch") if isinstance(row, dict) else None
    if isinstance(value, str) and value.strip():
        return value.strip(), SOURCE_REGISTRY
    branch, source = fleet_staging_branch()
    if repo is not None and row is None:
        source = f"{source}; registry unreachable or no row for this repo"
    return branch, source


def describe(branch, source):
    """One phrase for a log line: ``dev (project registry)``."""
    return f"{branch} ({source})"
