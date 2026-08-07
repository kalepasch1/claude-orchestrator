#!/usr/bin/env python3
"""Admission precondition for recovery-class tasks: no recovery without a recoverable input.

WHY THIS EXISTS
---------------
Of 21,146 tasks created, 2,499 produced code (11.8%). The single largest generator of
the 9,918 that produced nothing was `recover-*` at 2,450 (25%), and it was recursive.

The mechanism, exactly: `integration_sweeper` notices an agent branch is missing and
queues `recover-missing-branch-<slug>`, whose prompt asks the agent to "recreate the
smallest equivalent patch". But the branch is GONE — there is no diff, no artifact, no
commit, only a slug. The agent cannot recreate a patch it cannot see, so it produces
nothing. Before the evidence gate landed it was marked MERGED anyway, which left yet
another branch missing, which the sweeper detected, which queued another recovery. The
slugs record the recursion plainly:

    recover-missing-branch-improve-enhanced-error-handling-and-reporting-slice-5
    recover-missing-branch-rework-legal-rework-oversized-deploy-search-fns-...

This module refuses only the impossible case. Recovery WITH a real input is exactly
right and is how stranded branches come back; nothing here touches that path.

DESIGN CONSTRAINTS
------------------
* FAIL-SOFT. If the precondition check itself errors, the task is ALLOWED and an alarm
  is raised. An over-eager gate that blocks real recovery is worse than the gap.
* Operator-origin tasks are never gated. A human directive is a business input.
* Refusals are RECORDED in admission_rejections, never silently dropped — the whole
  failure mode being designed against is work disappearing without a trace.
"""
import os
import re
import subprocess

RECOVERY_PREFIX = "recover-missing-branch-"
DEFAULT_MAX_DEPTH = 2
GATE = "recovery_admission"
NO_INPUT_REASON = "no recoverable input"

# Slug shapes that carry recovery semantics. `rework-<n>-recover-missing-branch-<x>` is
# emitted by the repair path and is a recovery of a recovery just as much as a bare one.
_REWORK_RECOVERY = re.compile(r"^rework-.*?-(" + re.escape(RECOVERY_PREFIX) + r".*)$")


def max_depth():
    """Recursion ceiling, ORCH_RECOVERY_MAX_DEPTH (default 2)."""
    try:
        return max(1, int(os.environ.get("ORCH_RECOVERY_MAX_DEPTH", DEFAULT_MAX_DEPTH)))
    except (TypeError, ValueError):
        return DEFAULT_MAX_DEPTH


def is_recovery_slug(slug):
    """True for recovery-class slugs, bare or wrapped in a rework-* repair."""
    s = str(slug or "")
    return s.startswith(RECOVERY_PREFIX) or bool(_REWORK_RECOVERY.match(s))


def is_canary(slug):
    """Canaries are probes. They legitimately produce no code and are not recovery."""
    return str(slug or "").startswith("canary-")


def recovery_depth(slug):
    """Lineage depth from the slug chain.

    recover-missing-branch-foo                              -> 1
    recover-missing-branch-recover-missing-branch-foo       -> 2
    rework-7-recover-missing-branch-recover-missing-...-foo -> 2

    Counts EVERY occurrence of the prefix, not just leading ones. Measured against the
    live queue, recursion almost never nests as a literal doubled prefix (0 rows); it
    nests through the repair path — `recover-missing-branch-rework-N-<...>` (507 rows)
    and `rework-N-recover-missing-branch-<...>` (102 rows). A leading-prefix-only count
    scores those as depth 1 and the cap would never fire on the shape that actually
    recurses. A non-recovery slug is depth 0.
    """
    return str(slug or "").count(RECOVERY_PREFIX)


def recovery_root(slug):
    """The original slug a recovery chain is ultimately trying to recover."""
    s = str(slug or "")
    m = _REWORK_RECOVERY.match(s)
    if m:
        s = m.group(1)
    while s.startswith(RECOVERY_PREFIX):
        s = s[len(RECOVERY_PREFIX):]
    return s


# --------------------------------------------------------------------------- inputs

def _git_ok(repo, *args):
    try:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                              timeout=30).returncode == 0
    except Exception:
        return False


def branch_input(repo, slug):
    """The agent branch still exists locally or on origin — the work itself survives."""
    if not repo or not slug:
        return False
    branch = f"agent/{slug}"
    if _git_ok(repo, "rev-parse", "--verify", "--quiet", branch):
        return True
    if _git_ok(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"):
        return True
    try:
        r = subprocess.run(["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"],
                           cwd=repo, capture_output=True, text=True, timeout=60)
        return r.returncode == 0 and bool((r.stdout or "").strip())
    except Exception:
        return False


def commit_input(repo, sha):
    """A recorded artifact commit whose object is actually reachable."""
    if not repo or not sha:
        return False
    return _git_ok(repo, "cat-file", "-e", f"{str(sha).strip()}^{{commit}}")


class ProbeUnavailable(Exception):
    """A recoverable-input probe could not run (DB down, git unavailable, ...).

    This MUST stay distinct from "the probe ran and found nothing". Swallowing it and
    returning an empty result would make a database outage indistinguishable from an
    absent input, so a transient outage would refuse every genuine recovery in the fleet
    at once — the precise over-eager failure this gate is required not to have. Raised
    here, caught by check(), which then fails open with an alarm.
    """


def _rows(db_mod, table, params):
    try:
        return db_mod.select(table, params) or []
    except Exception as exc:
        raise ProbeUnavailable(f"{table} probe failed: {exc!r}") from exc


def stored_diff_input(db_mod, project_id, slug):
    """A stored patch survives even when the branch does not — that diff IS the input."""
    if not db_mod or not slug:
        return False
    for row in _rows(db_mod, "task_artifacts",
                     {"select": "patch_diff", "slug": f"eq.{slug}", "limit": "5"}):
        if str(row.get("patch_diff") or "").strip():
            return True
    for row in _rows(db_mod, "merged_diffs",
                     {"select": "diff", "slug": f"eq.{slug}", "limit": "5"}):
        if str(row.get("diff") or "").strip():
            return True
    return False


def find_recoverable_input(row, repo=None, db_mod=None):
    """Return the name of the first recoverable input found, else None.

    Checked in cost order: cheap local git refs before any network or DB read.
    """
    if db_mod is None:
        import db as db_mod  # noqa: PLC0415  (late import keeps this module test-friendly)

    slug = recovery_root(row.get("slug"))
    project_id = row.get("project_id")

    # integration_sweeper resolves result-cache / patch-transplant evidence before admission.
    # A non-empty reuse payload is the missing patch input even when the branch object is gone.
    if str(row.get("_reuse_context") or "").strip():
        return "reuse_context"

    if branch_input(repo, slug):
        return "branch"

    original = _rows(db_mod, "tasks",
                     {"select": "artifact_commit", "slug": f"eq.{slug}",
                      "project_id": f"eq.{project_id}", "limit": "1"})
    if original and commit_input(repo, original[0].get("artifact_commit")):
        return "artifact_commit"

    if stored_diff_input(db_mod, project_id, slug):
        return "stored_diff"

    return None


# ---------------------------------------------------------------------- the decision

class Decision(object):
    """(allowed, reason, gate). `alarm` is set when the gate itself failed open."""

    __slots__ = ("allowed", "reason", "gate", "input_kind", "alarm")

    def __init__(self, allowed, reason="", gate=GATE, input_kind=None, alarm=False):
        self.allowed = allowed
        self.reason = reason
        self.gate = gate
        self.input_kind = input_kind
        self.alarm = alarm

    def __bool__(self):
        return bool(self.allowed)

    __nonzero__ = __bool__

    def __repr__(self):
        return (f"Decision(allowed={self.allowed!r}, reason={self.reason!r}, "
                f"input_kind={self.input_kind!r}, alarm={self.alarm!r})")


def check(row, repo=None, db_mod=None):
    """Decide whether a recovery-class task may be queued. Never raises.

    Non-recovery tasks and operator directives pass straight through. Anything this
    module cannot evaluate is ALLOWED with alarm=True — see the fail-soft constraint.
    """
    try:
        if not isinstance(row, dict):
            return Decision(True, "not a task row")

        slug = str(row.get("slug") or "")
        if not is_recovery_slug(slug):
            return Decision(True, "not a recovery-class task")

        # An operator asking for a recovery is a business input, not fleet churn.
        try:
            import db as _db
            if _db._is_operator_origin(row):
                return Decision(True, "operator origin — never gated")
        except Exception:
            pass

        depth = recovery_depth(slug)
        ceiling = max_depth()
        if depth > ceiling:
            return Decision(
                False,
                f"recovery depth {depth} exceeds ORCH_RECOVERY_MAX_DEPTH={ceiling} "
                f"(root: {recovery_root(slug)}) — escalate to operator",
                input_kind=None)

        if repo is None:
            repo = row.get("_repo_path") or row.get("repo_path")

        found = find_recoverable_input(row, repo=repo, db_mod=db_mod)
        if found:
            return Decision(True, f"recoverable input: {found}", input_kind=found)

        return Decision(
            False,
            f"{NO_INPUT_REASON} for {recovery_root(slug)}: no agent branch on origin, "
            f"no artifact commit, no stored patch_diff or merged diff. There is nothing "
            f"to recreate.")
    except Exception as exc:                            # noqa: BLE001 — fail-soft is the point
        # An over-eager gate that blocks real recovery is worse than the gap.
        return Decision(True, f"admission check failed open: {exc!r}", alarm=True)


def enforce(row, repo=None, db_mod=None, record=True):
    """Apply the gate and record the outcome. Returns True if the task may be queued."""
    decision = check(row, repo=repo, db_mod=db_mod)

    if decision.alarm:
        print(f"[recovery_admission] ALARM: gate failed open for "
              f"{row.get('slug') if isinstance(row, dict) else row!r}: {decision.reason}",
              flush=True)
        return True

    if decision.allowed:
        return True

    if record:
        # Keep the gap VISIBLE. Invisible work is the failure mode being designed against.
        try:
            import db as _db
            _db._record_refusal(row, GATE, decision.reason)
        except Exception:
            pass
    print(f"[recovery_admission] refused {row.get('slug')}: {decision.reason}", flush=True)
    return False
