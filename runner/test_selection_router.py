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

# File-pattern → test-scope overrides
FILE_PATTERN_OVERRIDES = [
    (re.compile(r"\.md$"), "skip", "markdown-only"),
    (re.compile(r"\.txt$"), "skip", "text-only"),
    (re.compile(r"test.*\.py$|test.*\.ts$"), "full", "test file changed"),
    (re.compile(r"package\.json$|package-lock\.json$"), "full", "dependency change"),
    (re.compile(r"\.env"), "full", "env config change"),
]


def select_test_strategy(task_kind, changed_files=None):
    """Choose the test strategy for a task based on kind and changed files.

    Returns dict with 'cmd', 'scope', and 'reason'.
    """
    if not ENABLED:
        return {"cmd": FALLBACK_CMD, "scope": "full", "reason": "router disabled"}

    # Check file patterns first — they can escalate scope
    if changed_files:
        for pattern, scope, reason in FILE_PATTERN_OVERRIDES:
            for f in changed_files:
                if pattern.search(f) and scope == "full":
                    return {"cmd": FALLBACK_CMD, "scope": "full",
                            "reason": f"file override: {reason}"}

    # Look up by task kind
    strategy = TEST_STRATEGIES.get(task_kind)
    if strategy:
        return dict(strategy)

    # Default: full test suite
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
