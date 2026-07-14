#!/usr/bin/env python3
"""
ai_task_fixer.py — AI-driven task failure classification and repair routing.

Analyzes task failure logs/output to classify the failure category and generate
targeted repair prompts, replacing the generic "try again" loop with structured
diagnosis → fix → verify cycles.

Env vars:
    ORCH_AI_FIXER              "true" to enable (default "true")
    ORCH_AI_FIXER_MAX_LOG_CHARS  max chars of failure log to analyze (default 8000)
"""
import os
import re
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("ai_task_fixer")

ENABLED = os.environ.get("ORCH_AI_FIXER", "true").lower() in ("1", "true", "yes")
MAX_LOG_CHARS = int(os.environ.get("ORCH_AI_FIXER_MAX_LOG_CHARS", "8000"))

# ---------------------------------------------------------------------------
# Failure taxonomy
# ---------------------------------------------------------------------------
FAILURE_CATEGORIES = {
    "buildfail": {
        "patterns": [
            r"(?i)build\s+fail", r"(?i)compilation?\s+(error|fail)",
            r"(?i)tsc?\s+error", r"(?i)webpack.*error", r"(?i)module not found",
            r"(?i)syntaxerror", r"(?i)cannot find module",
        ],
        "priority": 1,
        "repair_strategy": "fix_build",
    },
    "testfail": {
        "patterns": [
            r"(?i)test\s+(fail|error)", r"(?i)assert(ion)?.*fail",
            r"(?i)FAIL\s+\S+\.test", r"(?i)expected.*received",
            r"(?i)pytest.*FAILED", r"(?i)\d+ failing", r"(?i)test suite failed",
        ],
        "priority": 2,
        "repair_strategy": "fix_tests",
    },
    "import_error": {
        "patterns": [
            r"(?i)importerror", r"(?i)modulenotfounderror",
            r"(?i)no module named", r"(?i)cannot resolve",
        ],
        "priority": 1,
        "repair_strategy": "fix_imports",
    },
    "type_error": {
        "patterns": [
            r"(?i)typeerror", r"(?i)type.*mismatch",
            r"(?i)is not assignable to", r"(?i)expected.*argument",
        ],
        "priority": 3,
        "repair_strategy": "fix_types",
    },
    "timeout": {
        "patterns": [
            r"(?i)timeout", r"(?i)timed?\s*out",
            r"(?i)deadline\s+exceeded", r"(?i)SIGTERM",
        ],
        "priority": 4,
        "repair_strategy": "reduce_scope",
    },
    "noop": {
        "patterns": [
            r"(?i)no\s+(committable\s+)?changes", r"(?i)nothing to commit",
            r"(?i)produced\s+no\s+.*changes",
        ],
        "priority": 5,
        "repair_strategy": "force_implementation",
    },
    "conflict": {
        "patterns": [
            r"(?i)merge\s+conflict", r"(?i)CONFLICT\s+\(",
            r"(?i)conflict.*resolved", r"(?i)rebase.*conflict",
        ],
        "priority": 2,
        "repair_strategy": "resolve_conflict",
    },
    "permission": {
        "patterns": [
            r"(?i)permission\s+denied", r"(?i)EACCES",
            r"(?i)Operation not permitted", r"(?i)403\s+Forbidden",
        ],
        "priority": 1,
        "repair_strategy": "fix_permissions",
    },
}

# Compiled pattern cache
_compiled = {}
_compile_lock = threading.Lock()


def _get_compiled():
    """Lazily compile all patterns."""
    with _compile_lock:
        if not _compiled:
            for cat, info in FAILURE_CATEGORIES.items():
                _compiled[cat] = [re.compile(p) for p in info["patterns"]]
    return _compiled


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
def classify_failure(log_text):
    """Classify a failure log into a category.

    Returns dict with 'category', 'confidence', 'matched_pattern', 'repair_strategy'.
    Falls back to 'unknown' category on no match.
    """
    if not log_text:
        return {
            "category": "unknown",
            "confidence": 0.0,
            "matched_pattern": None,
            "repair_strategy": "generic_retry",
        }

    truncated = log_text[-MAX_LOG_CHARS:] if len(log_text) > MAX_LOG_CHARS else log_text
    compiled = _get_compiled()

    matches = []
    for cat, patterns in compiled.items():
        for pat in patterns:
            m = pat.search(truncated)
            if m:
                matches.append({
                    "category": cat,
                    "confidence": 0.9,
                    "matched_pattern": m.group(0),
                    "repair_strategy": FAILURE_CATEGORIES[cat]["repair_strategy"],
                    "priority": FAILURE_CATEGORIES[cat]["priority"],
                })
                break  # one match per category is enough

    if not matches:
        return {
            "category": "unknown",
            "confidence": 0.0,
            "matched_pattern": None,
            "repair_strategy": "generic_retry",
        }

    # Return highest priority (lowest number) match
    matches.sort(key=lambda m: m["priority"])
    best = matches[0]
    del best["priority"]
    return best


def classify_all(log_text):
    """Return all matching failure categories, sorted by priority."""
    if not log_text:
        return []

    truncated = log_text[-MAX_LOG_CHARS:] if len(log_text) > MAX_LOG_CHARS else log_text
    compiled = _get_compiled()

    results = []
    for cat, patterns in compiled.items():
        for pat in patterns:
            m = pat.search(truncated)
            if m:
                results.append({
                    "category": cat,
                    "confidence": 0.9,
                    "matched_pattern": m.group(0),
                    "repair_strategy": FAILURE_CATEGORIES[cat]["repair_strategy"],
                })
                break

    results.sort(key=lambda r: FAILURE_CATEGORIES[r["category"]]["priority"])
    return results


# ---------------------------------------------------------------------------
# Repair prompt generation
# ---------------------------------------------------------------------------
_REPAIR_TEMPLATES = {
    "fix_build": (
        "The previous attempt failed with a build error: {matched_pattern}\n"
        "Steps:\n1. Read the build error output carefully\n"
        "2. Fix the source file(s) causing the error\n"
        "3. Run the build command to verify the fix\n"
        "4. Commit the fix"
    ),
    "fix_tests": (
        "The previous attempt failed tests: {matched_pattern}\n"
        "Steps:\n1. Read the test failure output\n"
        "2. Fix the source code (not the test assertions, unless the test is wrong)\n"
        "3. Re-run the failing tests to confirm they pass\n"
        "4. Commit the fix"
    ),
    "fix_imports": (
        "The previous attempt had an import error: {matched_pattern}\n"
        "Steps:\n1. Check which module is missing or misnamed\n"
        "2. Install the dependency or fix the import path\n"
        "3. Verify the import resolves\n"
        "4. Commit the fix"
    ),
    "fix_types": (
        "The previous attempt had a type error: {matched_pattern}\n"
        "Steps:\n1. Identify the type mismatch\n"
        "2. Fix the type annotation or the value being passed\n"
        "3. Run type checking to verify\n"
        "4. Commit the fix"
    ),
    "reduce_scope": (
        "The previous attempt timed out: {matched_pattern}\n"
        "Steps:\n1. Identify the operation that's taking too long\n"
        "2. Reduce scope or optimize the slow operation\n"
        "3. Add a timeout guard if appropriate\n"
        "4. Commit the fix"
    ),
    "force_implementation": (
        "The previous attempt produced no changes.\n"
        "Steps:\n1. Read the task prompt carefully\n"
        "2. Make the smallest concrete implementation that satisfies the requirement\n"
        "3. Ensure at least one file is modified and committed\n"
        "4. Add a test if appropriate"
    ),
    "resolve_conflict": (
        "The previous attempt had a merge conflict: {matched_pattern}\n"
        "Steps:\n1. Identify the conflicting files\n"
        "2. Rebase onto the latest base branch\n"
        "3. Resolve conflicts preserving both sets of changes where possible\n"
        "4. Commit the resolution"
    ),
    "fix_permissions": (
        "The previous attempt had a permission error: {matched_pattern}\n"
        "Steps:\n1. Identify which file or operation needs different permissions\n"
        "2. Fix file permissions or use a different approach\n"
        "3. Verify the operation succeeds\n"
        "4. Commit any changes"
    ),
    "generic_retry": (
        "The previous attempt failed with an unclassified error.\n"
        "Steps:\n1. Read any error output from the previous run\n"
        "2. Inspect the repository state and task artifacts\n"
        "3. Fix the root cause\n"
        "4. Run checks and commit"
    ),
}


def generate_repair_prompt(classification, original_prompt=""):
    """Generate a targeted repair prompt based on failure classification.

    Args:
        classification: dict from classify_failure()
        original_prompt: the original task prompt to prepend

    Returns:
        str: the repair prompt
    """
    strategy = classification.get("repair_strategy", "generic_retry")
    template = _REPAIR_TEMPLATES.get(strategy, _REPAIR_TEMPLATES["generic_retry"])
    matched = classification.get("matched_pattern", "unknown error")

    repair_section = template.format(matched_pattern=matched or "unknown error")

    parts = []
    if original_prompt:
        parts.append(f"Original task:\n{original_prompt[:4000]}")
    parts.append(f"\nRepair directive ({classification.get('category', 'unknown')}):\n{repair_section}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
_stats_lock = threading.Lock()
_stats = {"classifications": 0, "repairs_generated": 0, "unknown": 0}


def stats():
    with _stats_lock:
        return dict(_stats)


def reset_stats():
    with _stats_lock:
        for k in _stats:
            _stats[k] = 0
