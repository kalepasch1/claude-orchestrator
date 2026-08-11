#!/usr/bin/env python3
"""
test_selection_router.py — Dynamic test selection based on task type and dependencies.

Routes tasks to the appropriate test suite/command based on their kind, affected
files, and dependency graph. Reduces CI time by running only relevant tests
instead of the full suite for every change.

Env vars:
    ORCH_TEST_ROUTER_ENABLED    "true" (default) / "false"
    ORCH_TEST_ROUTER_FALLBACK   fallback test command (default "npm test")
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("test_selection_router")

ENABLED = os.environ.get("ORCH_TEST_ROUTER_ENABLED", "true").lower() == "true"
FALLBACK_CMD = os.environ.get("ORCH_TEST_ROUTER_FALLBACK", "npm test")

# Task kind -> test strategy mapping
TEST_STRATEGIES = {
    "docs": {"cmd": "true", "scope": "skip", "reason": "docs-only change"},
    "chore": {"cmd": "true", "scope": "skip", "reason": "chore/maintenance"},
    "lint": {"cmd": "npm run lint", "scope": "lint", "reason": "lint-only"},
    "format": {"cmd": "true", "scope": "skip", "reason": "format-only"},
    "test": {"cmd": "npm test", "scope": "full", "reason": "test change needs full run"},
    "bugfix": {"cmd": "npm test", "scope": "full", "reason": "bugfix needs full validation"},
    "build": {"cmd": "npm test", "scope": "full", "reason": "build task"},
    "canary": {"cmd": "npm test", "scope": "targeted", "reason": "canary — minimal scope"},
    "mechanical": {"cmd": "npm test", "scope": "targeted", "reason": "mechanical change"},
}

# File-pattern → test-scope overrides.
# "full" entries escalate: one match forces the whole suite.
# "skip" entries only permit an early exit if EVERY changed file matches one.
FILE_PATTERN_OVERRIDES = [
    (re.compile(r"\.md$"), "skip", "markdown-only"),
    (re.compile(r"\.txt$"), "skip", "text-only"),
    (re.compile(r"test.*\.py$|test.*\.ts$"), "full", "test file changed"),
    (re.compile(r"package\.json$|package-lock\.json$"), "full", "dependency change"),
    (re.compile(r"\.env"), "full", "env config change"),
]

_ESCALATE = [(p, r) for p, s, r in FILE_PATTERN_OVERRIDES if s == "full"]
_SKIPPABLE = [(p, r) for p, s, r in FILE_PATTERN_OVERRIDES if s == "skip"]


def _escalation_reason(changed_files):
    """First pattern that forces a full run, or None."""
    for pattern, reason in _ESCALATE:
        for f in changed_files:
            if pattern.search(f):
                return reason
    return None


def _all_files_are_skippable(changed_files):
    """True only if every changed file matches a skip pattern.

    The skip entries in FILE_PATTERN_OVERRIDES used to be unreachable — the
    override loop tested `scope == "full"` and ignored everything else — so
    "is this diff actually inert?" was never asked. It is asked here, and it
    is asked of ALL files: one unrecognised path is enough to deny the skip.
    """
    return all(any(p.search(f) for p, _ in _SKIPPABLE) for f in changed_files)


def select_test_strategy(task_kind, changed_files=None):
    """Choose the test strategy for a task based on kind and changed files.

    Returns dict with 'cmd', 'scope', and 'reason'.

    Precedence, strongest first:
      1. an escalating file pattern (test file, dependency, env) -> full
      2. a kind that skips, but ONLY if every changed file is inert
      3. the kind's own strategy
      4. full

    Rule 2 is the value-aware part. Previously a kind of docs/chore/format
    returned scope=skip on the strength of the label alone, so a task tagged
    "docs" that edited runner/db.py ran no tests at all. The label is now a
    proposal that the diff has to corroborate.
    """
    if not ENABLED:
        return {"cmd": FALLBACK_CMD, "scope": "full", "reason": "router disabled"}

    changed_files = list(changed_files or [])
    strategy = TEST_STRATEGIES.get(task_kind)

    if changed_files:
        reason = _escalation_reason(changed_files)
        if reason:
            return {"cmd": FALLBACK_CMD, "scope": "full",
                    "reason": f"file override: {reason}"}

        # A skip proposed by the kind has to survive the diff.
        if strategy and strategy["scope"] == "skip" and not _all_files_are_skippable(changed_files):
            return {"cmd": FALLBACK_CMD, "scope": "full",
                    "reason": f"kind '{task_kind}' proposed skip but the diff "
                              f"touches non-inert files"}

        # Conversely, an inert diff earns an early exit even from a kind that
        # would otherwise have run the full suite.
        if not strategy or strategy["scope"] != "skip":
            if _all_files_are_skippable(changed_files):
                return {"cmd": "true", "scope": "skip",
                        "reason": "file override: all changed files are inert"}

    if strategy:
        return dict(strategy)

    return {"cmd": FALLBACK_CMD, "scope": "full", "reason": f"unknown kind '{task_kind}'"}


def should_skip_tests(task_kind, changed_files=None):
    """Quick check: can we skip tests entirely for this task?"""
    strategy = select_test_strategy(task_kind, changed_files)
    return strategy["scope"] == "skip"


def get_test_command(task_kind, changed_files=None, project_test_cmd=None):
    """Return the test command to run, respecting project overrides."""
    strategy = select_test_strategy(task_kind, changed_files)
    if strategy["scope"] == "skip":
        return "true"  # no-op
    if project_test_cmd and strategy["scope"] == "full":
        return project_test_cmd
    return strategy["cmd"]


def route_summary(tasks):
    """Batch-route a list of tasks. Returns per-scope counts for dashboards."""
    counts = {"skip": 0, "lint": 0, "targeted": 0, "full": 0}
    for t in tasks:
        strategy = select_test_strategy(t.get("kind", "build"))
        scope = strategy["scope"]
        counts[scope] = counts.get(scope, 0) + 1
    return counts


if __name__ == "__main__":
    import json
    # Demo: route common task kinds
    for kind in sorted(TEST_STRATEGIES.keys()):
        s = select_test_strategy(kind)
        print(f"  {kind:12s} -> scope={s['scope']:8s} cmd={s['cmd']}")
    print(f"\n  fallback     -> {select_test_strategy('unknown')}")
