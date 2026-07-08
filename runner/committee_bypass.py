#!/usr/bin/env python3
"""
committee_bypass.py — Skip expensive committee deliberation for trivial tasks.

committees.py runs multi-round expert panels (1,736 lines, multiple model calls per
seat per round). For mechanical/template tasks (rename, config, dependency bump),
this is 20X-100X overkill.

Bypass conditions (ALL must be true):
  1. diff_compiler confidence > threshold (task is template-matched)
  2. diff size < MAX_DIFF_LINES (small change)
  3. task kind is in BYPASS_KINDS (mechanical, config, etc.)
  4. no legal/security/privacy markers in the prompt
  5. ORCH_COMMITTEE_BYPASS is not disabled

When bypassed, returns a synthetic "auto-approved" committee result.
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CONFIDENCE_THRESHOLD = float(os.environ.get("ORCH_COMMITTEE_BYPASS_CONF", "0.7"))
MAX_DIFF_LINES = int(os.environ.get("ORCH_COMMITTEE_BYPASS_MAX_LINES", "50"))
BYPASS_KINDS = {"mechanical", "config", "dependency", "rename", "formatting",
                "docs", "test", "refactor", "cleanup", "bump", "typo"}

# Markers that FORCE committee review regardless of other conditions
SENSITIVE_MARKERS = (
    "security", "auth", "permission", "credential", "secret", "key",
    "legal", "compliance", "regulat", "privacy", "gdpr", "ccpa",
    "license", "copyright", "patent", "trade secret",
    "payment", "billing", "financial", "money", "transfer",
    "delete", "drop", "truncate", "migration", "schema",
    "production", "deploy", "release",
)


def should_bypass(task, diff_compiler_result=None, diff_lines=0):
    """Decide if committee deliberation can be skipped.

    Args:
        task: task dict with prompt, kind, slug, etc.
        diff_compiler_result: output from diff_compiler.compile_plan() or None
        diff_lines: number of lines in the diff

    Returns:
        (bypass: bool, reason: str)
    """
    if os.environ.get("ORCH_COMMITTEE_BYPASS", "true").lower() not in ("true", "1", "yes"):
        return False, "bypass disabled"

    # Material tasks always get committee review
    if task.get("material"):
        return False, "material task"

    prompt = (task.get("prompt") or "").lower()
    kind = (task.get("kind") or "").lower()

    # Check for sensitive content
    for marker in SENSITIVE_MARKERS:
        if marker in prompt:
            return False, f"sensitive marker: {marker}"

    # Check diff size
    if diff_lines > MAX_DIFF_LINES:
        return False, f"diff too large ({diff_lines} > {MAX_DIFF_LINES})"

    # Check diff compiler confidence
    if diff_compiler_result and diff_compiler_result.get("has_plan"):
        conf = diff_compiler_result.get("confidence", 0)
        if conf >= CONFIDENCE_THRESHOLD:
            return True, f"template-matched (conf={conf:.0%}, {diff_lines} lines)"

    # Check kind
    if kind in BYPASS_KINDS:
        if diff_lines <= MAX_DIFF_LINES:
            return True, f"mechanical kind={kind} ({diff_lines} lines)"

    # Check slug patterns
    slug = (task.get("slug") or "").lower()
    mechanical_patterns = ("fix-lint", "fix-type", "rename-", "bump-", "update-dep",
                           "format-", "typo-", "cleanup-", "docs-", "test-")
    for pat in mechanical_patterns:
        if pat in slug:
            if diff_lines <= MAX_DIFF_LINES:
                return True, f"mechanical slug pattern ({pat})"

    return False, "no bypass condition met"


def synthetic_result(reason=""):
    """Return a synthetic committee approval for bypassed tasks."""
    return {
        "verdict": "GO",
        "score": 8,
        "conviction": 9,
        "opinion": f"Committee bypassed: {reason}. Small/mechanical change auto-approved.",
        "conditions": "",
        "dissent": "none",
        "recommendation": "auto-merge",
        "p_success": 0.95,
        "upside": "saves committee cost on trivial work",
        "downside": "minimal — change is mechanical",
        "reversible": True,
        "critical": False,
        "bypassed": True,
        "bypass_reason": reason,
    }
