#!/usr/bin/env python3
"""
test_result_aggregator.py — aggregate test results across task branches.

Collects pass/fail results from task CI runs and identifies flaky tests,
consistently failing modules, and overall test health trends.

Env vars:
    ORCH_TEST_AGG_ENABLED   "true" to enable (default "true")
"""
import os
import sys
import re
import collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENABLED = os.environ.get("ORCH_TEST_AGG_ENABLED", "true").lower() in ("1", "true", "yes")

# Patterns to extract test results from task notes
_PASS_RE = re.compile(r"(\d+)\s*(?:tests?\s*)?pass", re.I)
_FAIL_RE = re.compile(r"(\d+)\s*(?:tests?\s*)?fail", re.I)
_ERROR_RE = re.compile(r"tests?\s*failed|build\s*fail|tsc.*error", re.I)


def parse_test_note(note):
    """Extract pass/fail counts from a task note string."""
    if not note:
        return {"passed": 0, "failed": 0, "has_error": False}
    passed = 0
    failed = 0
    for m in _PASS_RE.finditer(note):
        passed += int(m.group(1))
    for m in _FAIL_RE.finditer(note):
        failed += int(m.group(1))
    has_error = bool(_ERROR_RE.search(note))
    return {"passed": passed, "failed": failed, "has_error": has_error}


def aggregate(project_id=None):
    """Aggregate test results from recent DONE/MERGED/QUARANTINED tasks.

    Returns dict with overall stats and per-kind breakdown.
    """
    if not ENABLED:
        return {}
    try:
        import db
    except ImportError:
        return {}

    filters = {"select": "slug,kind,note,state"}
    if project_id:
        filters["project_id"] = f"eq.{project_id}"
    filters["state"] = "in.(DONE,MERGED,QUARANTINED,BLOCKED)"
    rows = db.select("tasks", filters) or []

    total_passed = 0
    total_failed = 0
    tasks_with_errors = 0
    kind_stats = collections.defaultdict(lambda: {"passed": 0, "failed": 0, "count": 0})

    for r in rows:
        result = parse_test_note(r.get("note", ""))
        total_passed += result["passed"]
        total_failed += result["failed"]
        if result["has_error"]:
            tasks_with_errors += 1
        kind = r.get("kind", "unknown")
        kind_stats[kind]["passed"] += result["passed"]
        kind_stats[kind]["failed"] += result["failed"]
        kind_stats[kind]["count"] += 1

    total = total_passed + total_failed
    pass_rate = (total_passed / total * 100) if total > 0 else 0.0

    return {
        "total_tasks": len(rows),
        "tasks_with_errors": tasks_with_errors,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "pass_rate": round(pass_rate, 1),
        "by_kind": dict(kind_stats),
    }


def run():
    result = aggregate()
    if not result:
        print("test_result_aggregator: disabled or no data")
        return {}
    print(f"test_result_aggregator: {result['total_tasks']} tasks, "
          f"pass rate {result['pass_rate']}%, {result['tasks_with_errors']} with errors")
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
