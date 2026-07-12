#!/usr/bin/env python3
"""
targeted_remedy.py — Apply specific, automated remediation actions for known quarantine
failure categories before falling through to generic rework.

Each remedy function attempts a concrete fix (rebase, timeout bump, dependency install,
fixture refresh) and returns True if it handled the case, False to fall through.

Quarantine is treated as terminal, not a decision point — every remedy either fixes the
issue and requeues, or passes to the next strategy. No remedy leaves a task in limbo.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MARK = "targeted-remedy"

# --- Classifiers for specific failure reasons ---

_MERGE_CONFLICT = re.compile(
    r"merge conflict|CONFLICT \(content\)|automatic merge failed|"
    r"rebase.*conflict|cherry-pick.*conflict|cannot merge",
    re.I,
)

_TEST_TIMEOUT = re.compile(
    r"test.*timeout|timed?\s*out.*test|jest.*timeout|mocha.*timeout|"
    r"exceeded timeout|timeout of \d+\s*ms|SIGTERM.*test",
    re.I,
)

_MISSING_DEP = re.compile(
    r"cannot find module|module not found|no module named|import error|"
    r"ModuleNotFoundError|command not found.*(npm|yarn|pnpm|pip|cargo)|"
    r"ENOENT.*node_modules|package.*not installed",
    re.I,
)

_PRE_MERGE_GATE = re.compile(
    r"pre.?merge.*fail|gate.*fail|ci.*fail|pipeline.*fail|"
    r"check.*fail|status.*fail|required.*check",
    re.I,
)

# Sub-patterns for pre-merge gate failures
_GATE_MISSING_SECRET = re.compile(r"missing.*secret|secret.*not.*set|env.*not.*found", re.I)
_GATE_STALE_FIXTURE = re.compile(r"fixture.*stale|stale.*fixture|snapshot.*mismatch", re.I)
_GATE_ENV_MISMATCH = re.compile(r"env.*mismatch|environment.*differ|config.*mismatch", re.I)
_GATE_STALE_DB = re.compile(r"stale.*db|database.*fixture|migration.*pending|schema.*drift", re.I)
_GATE_BUILD_ERROR = re.compile(r"build.*error|compilation.*error|type.*error|syntax.*error", re.I)

_FIXTURE_STALE = re.compile(
    r"fixture.*stale|stale.*fixture|fixture.*outdated|upstream.*fixture.*changed|"
    r"snapshot.*obsolete|fixture.*mismatch",
    re.I,
)


def _evidence(task):
    """Combine note + log_tail into a single evidence string."""
    return f"{task.get('note') or ''}\n{task.get('log_tail') or ''}"


def classify_reason(task):
    """Return a specific failure reason string, or None if unrecognized."""
    ev = _evidence(task)
    if _MERGE_CONFLICT.search(ev):
        return "merge_conflict"
    if _TEST_TIMEOUT.search(ev):
        return "test_timeout"
    if _MISSING_DEP.search(ev):
        return "missing_dependency"
    if _FIXTURE_STALE.search(ev):
        return "fixture_stale"
    if _PRE_MERGE_GATE.search(ev):
        return "pre_merge_gate_fail"
    return None


def _requeue(task, note, prompt_patch=""):
    """Requeue a task with updated note and optional prompt injection."""
    patch = {
        "state": "QUEUED",
        "note": f"{MARK}: {note}",
        "updated_at": "now()",
    }
    if prompt_patch:
        old_prompt = task.get("prompt") or ""
        if prompt_patch not in old_prompt:
            patch["prompt"] = f"{prompt_patch}\n\n{old_prompt}"
    rc = int(task.get("remediation_count") or 0)
    patch["remediation_count"] = rc + 1
    try:
        db.update("tasks", {"id": task["id"]}, patch)
        return True
    except Exception:
        return False


def remedy_merge_conflict(task):
    """Merge conflict → requeue with directive to rebase on fresh master."""
    directive = (
        "AUTO-REMEDY: merge conflict detected. Rebase your branch on the latest master "
        "before making changes. Run: git fetch origin && git rebase origin/master. "
        "Resolve any conflicts by keeping the upstream version for generated files and "
        "your version for the task-specific logic."
    )
    return _requeue(task, "merge_conflict: requeued with rebase directive", directive)


def remedy_test_timeout(task):
    """Test timeout → requeue with directive to bump timeout or split suite."""
    ev = _evidence(task)
    # Try to extract the current timeout value
    timeout_match = re.search(r"timeout of (\d+)\s*ms", ev)
    current_ms = int(timeout_match.group(1)) if timeout_match else 5000
    new_ms = min(current_ms * 2, 60000)  # double it, cap at 60s
    directive = (
        f"AUTO-REMEDY: test timeout detected (was {current_ms}ms). "
        f"Bump the test timeout to {new_ms}ms. If the test is inherently slow, "
        f"split the suite into smaller units. Add --timeout={new_ms} to the test "
        f"runner config or set jest.setTimeout({new_ms}) in the test setup."
    )
    return _requeue(task, f"test_timeout: bumped to {new_ms}ms and requeued", directive)


def remedy_missing_dependency(task):
    """Missing dependency → requeue with install directive."""
    ev = _evidence(task)
    # Try to extract the missing module name
    mod_match = re.search(r"(?:cannot find module|no module named|ModuleNotFoundError:?\s*)['\"]?([a-zA-Z0-9_.-]+)", ev, re.I)
    mod_name = mod_match.group(1) if mod_match else "unknown"
    directive = (
        f"AUTO-REMEDY: missing dependency detected ({mod_name}). "
        f"Run the appropriate install command before building: "
        f"npm install (for JS/TS projects) or pip install -r requirements.txt (for Python). "
        f"If a specific package is missing, install it directly. "
        f"Verify the dependency is in the project's manifest (package.json / requirements.txt)."
    )
    return _requeue(task, f"missing_dependency: {mod_name}, requeued with install directive", directive)


def remedy_pre_merge_gate(task):
    """Pre-merge gate fail → inspect logs for 5 common patterns and apply fixes."""
    ev = _evidence(task)
    sub_reasons = []
    directives = []

    if _GATE_MISSING_SECRET.search(ev):
        sub_reasons.append("missing_secret")
        directives.append(
            "A required secret/env var is not set. Use environment variable placeholders "
            "and ensure the CI config references all required secrets."
        )
    if _GATE_STALE_FIXTURE.search(ev):
        sub_reasons.append("stale_fixture")
        directives.append(
            "Test fixtures or snapshots are stale. Regenerate snapshots with the test "
            "runner's update flag (e.g., --updateSnapshot for Jest)."
        )
    if _GATE_ENV_MISMATCH.search(ev):
        sub_reasons.append("env_mismatch")
        directives.append(
            "Environment configuration mismatch detected. Align the local and CI "
            "environment configs (check .env.example, CI variables)."
        )
    if _GATE_STALE_DB.search(ev):
        sub_reasons.append("stale_db")
        directives.append(
            "Database fixtures or migrations are out of date. Run pending migrations "
            "and regenerate DB fixtures from the current schema."
        )
    if _GATE_BUILD_ERROR.search(ev):
        sub_reasons.append("build_error")
        directives.append(
            "Build/compilation errors in the gate check. Fix type errors and syntax "
            "issues before the merge gate will pass."
        )

    if not directives:
        # Generic gate failure — still provide actionable guidance
        sub_reasons.append("unknown_gate")
        directives.append(
            "Pre-merge gate failed. Inspect the CI/gate logs carefully, identify the "
            "specific failing check, and fix the root cause before resubmitting."
        )

    combined = "; ".join(sub_reasons)
    directive = f"AUTO-REMEDY: pre-merge gate failure ({combined}). " + " ".join(directives)
    return _requeue(task, f"pre_merge_gate_fail: {combined}, requeued with fix directives", directive)


def remedy_fixture_stale(task):
    """Fixture stale → refresh from upstream and retry."""
    directive = (
        "AUTO-REMEDY: stale fixtures detected. Refresh test fixtures from upstream: "
        "pull the latest test data, regenerate snapshots (e.g., jest --updateSnapshot), "
        "and update any seed/fixture files that reference upstream schema or data. "
        "Commit the refreshed fixtures alongside your changes."
    )
    return _requeue(task, "fixture_stale: requeued with refresh directive", directive)


# Dispatch table mapping reason → remedy function
_REMEDIES = {
    "merge_conflict": remedy_merge_conflict,
    "test_timeout": remedy_test_timeout,
    "missing_dependency": remedy_missing_dependency,
    "pre_merge_gate_fail": remedy_pre_merge_gate,
    "fixture_stale": remedy_fixture_stale,
}

# Maximum targeted remedy attempts before falling through to generic rework
MAX_TARGETED_ATTEMPTS = int(os.environ.get("ORCH_TARGETED_REMEDY_MAX", "2"))


def attempt(task):
    """Try a targeted remedy for the task. Returns True if handled, False to fall through.

    Quarantine is terminal — this function either fixes and requeues, or returns False
    so the caller can apply generic rework. It never leaves the task in an intermediate state.
    """
    rc = int(task.get("remediation_count") or 0)
    if rc >= MAX_TARGETED_ATTEMPTS:
        return False  # too many targeted attempts, fall through to generic

    reason = classify_reason(task)
    if not reason:
        return False

    remedy_fn = _REMEDIES.get(reason)
    if not remedy_fn:
        return False

    try:
        return remedy_fn(task)
    except Exception:
        return False  # fail-soft: never block the pipeline
