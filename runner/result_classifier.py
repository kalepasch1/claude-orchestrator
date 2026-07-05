#!/usr/bin/env python3
"""
result_classifier.py - classify task results and detect non-task metadata objects.

When Claude Code times out or returns a metadata object instead of a diff-producing result,
we detect it here and handle it gracefully (log warning, return empty diff, continue).
"""


def is_error_max_turns(result):
    """Check if a result is a max_turns metadata object (not a real task result).

    Returns True if result has subtype='error_max_turns', indicating the agent
    hit the max_turns limit and produced no diff.
    """
    if not isinstance(result, dict):
        return False
    return result.get("subtype") == "error_max_turns" and result.get("stop_reason") == "tool_use"


def classify(result):
    """Classify a result object into categories.

    Returns a dict with:
    - 'type': 'error_max_turns' | 'error' | 'task_result' | 'unknown'
    - 'is_error': bool
    """
    if not isinstance(result, dict):
        return {"type": "unknown", "is_error": False}

    if is_error_max_turns(result):
        return {"type": "error_max_turns", "is_error": True}

    if result.get("is_error"):
        return {"type": "error", "is_error": True}

    if "result" in result or "text" in result:
        return {"type": "task_result", "is_error": False}

    return {"type": "unknown", "is_error": False}
