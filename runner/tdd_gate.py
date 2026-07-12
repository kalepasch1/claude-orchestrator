#!/usr/bin/env python3
"""
tdd_gate.py - TDD-first workflow enforcement for agent task execution.

Structurally enforces test-driven development: agent writes failing tests +
explicit acceptance criteria BEFORE coding, then implements to green. Task
status transitions to 'DONE' only when tests pass in the pytest build gate.

Configuration (fleet_config keys):
  ORCH_TDD_ENABLED - global gate (bool, default false)
  ORCH_TDD_TASK_KINDS - CSV of task kinds that require TDD (default: "feature,new-module")
  Example: 'feature,new-module,refactor'
  Fail-soft: returns empty list if key missing/unavailable

Key functions:
  - is_tdd_enabled() - read ORCH_TDD_ENABLED from fleet_config
  - get_task_kinds() - read ORCH_TDD_TASK_KINDS from fleet_config
  - is_tdd_gated(kind) - check if a task kind requires TDD
  - extract_test_file_path(agent_output) - parse test file path from agent output
  - parse_acceptance_criteria(test_code) - extract criterion docstrings from test file
  - validate_acceptance_criteria(task_spec) - check acceptance criteria format
  - run_must_pass_tests(test_file_path, must_pass_tests) - run gated tests via pytest
"""
import os
import sys
import re
import json
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_TDD_CACHE = {"enabled": None, "kinds": None, "cached_at": 0.0}


def is_tdd_enabled():
    """Read ORCH_TDD_ENABLED from fleet_config or environment. Default: false."""
    import time
    now = time.time()

    if _TDD_CACHE["enabled"] is not None and (now - _TDD_CACHE["cached_at"]) < 30:
        return _TDD_CACHE["enabled"]

    enabled = False
    try:
        import db
        rows = db.select("fleet_config", {"select": "key,value", "key": "eq.ORCH_TDD_ENABLED"}) or []
        if rows:
            value = str(rows[0].get("value", "false")).lower()
            enabled = value in ("true", "1", "yes")
    except Exception:
        pass

    if not enabled:
        enabled = os.environ.get("ORCH_TDD_ENABLED", "false").lower() in ("true", "1", "yes")

    _TDD_CACHE["enabled"] = enabled
    _TDD_CACHE["cached_at"] = now
    return enabled


def get_task_kinds():
    """
    Read ORCH_TDD_TASK_KINDS from fleet_config or environment.
    Returns a set of task kind identifiers that require TDD.
    Default: {"feature", "new-module"}
    """
    import time
    now = time.time()

    if _TDD_CACHE["kinds"] is not None and (now - _TDD_CACHE["cached_at"]) < 30:
        return _TDD_CACHE["kinds"]

    kinds_set = set()
    default_kinds = {"feature", "new-module"}

    try:
        import db
        rows = db.select("fleet_config", {"select": "key,value", "key": "eq.ORCH_TDD_TASK_KINDS"}) or []
        if rows:
            value = rows[0].get("value")
            if value:
                kinds_set = set(k.strip().lower() for k in str(value).split(",") if k.strip())
    except Exception:
        pass

    if not kinds_set:
        kinds_set = os.environ.get("ORCH_TDD_TASK_KINDS", "feature,new-module").lower().split(",")
        kinds_set = set(k.strip() for k in kinds_set if k.strip())

    if not kinds_set:
        kinds_set = default_kinds

    _TDD_CACHE["kinds"] = kinds_set
    _TDD_CACHE["cached_at"] = now
    return kinds_set


def is_tdd_gated(task_kind):
    """Check if a task kind is gated for TDD-first execution."""
    if not task_kind or not is_tdd_enabled():
        return False
    kinds = get_task_kinds()
    return task_kind.lower() in {k.lower() for k in kinds}


def extract_test_file_path(agent_output):
    """
    Extract the test file path from agent output.
    Looks for patterns like "tests/test_<task_id>.py" or "saved to: ...tests/..."
    Returns path relative to repo root, or None if not found.
    """
    if not agent_output:
        return None

    patterns = [
        r"tests/test_\w+\.py",
        r"saved to:?\s+(.*tests/test_\w+\.py)",
        r"write to:?\s+(.*tests/test_\w+\.py)",
        r"file:?\s+(.*tests/test_\w+\.py)",
    ]

    for pattern in patterns:
        m = re.search(pattern, agent_output, re.IGNORECASE)
        if m:
            path = m.group(1) if "(" in pattern and ")" in pattern else m.group(0)
            return path.strip()

    return None


def parse_acceptance_criteria(test_code):
    """
    Extract acceptance criteria (test docstrings) from a test file.
    Returns a list of dicts: {"test_name": str, "criterion": str}
    Each test docstring IS the acceptance criterion.
    """
    criteria = []

    pattern = r'def\s+(test_\w+)\s*\([^)]*\)\s*:\s*"""([^"]*)"""'

    for match in re.finditer(pattern, test_code, re.DOTALL):
        test_name = match.group(1)
        docstring = match.group(2).strip()
        if docstring.startswith("[ACCEPTANCE CRITERION]:"):
            criterion = docstring.replace("[ACCEPTANCE CRITERION]:", "").strip()
        else:
            criterion = docstring
        criteria.append({"test_name": test_name, "criterion": criterion})

    return criteria


def validate_acceptance_criteria(task_spec):
    """
    Validate acceptance criteria format in a task spec.
    Expected structure: {
        "metrics": {key: measurable_value, ...},
        "edge_cases": [case1, case2, ...],
        "must_pass_tests": [test_name1, test_name2, ...]
    }
    Returns (valid: bool, error_msg: str or None)
    """
    if not isinstance(task_spec, dict):
        return False, "Task spec must be a dict"

    criteria = task_spec.get("acceptance_criteria", {})
    if not isinstance(criteria, dict):
        return False, "acceptance_criteria must be a dict"

    metrics = criteria.get("metrics", {})
    if not isinstance(metrics, dict):
        return False, "metrics must be a dict"

    edge_cases = criteria.get("edge_cases", [])
    if not isinstance(edge_cases, list):
        return False, "edge_cases must be a list"

    must_pass = criteria.get("must_pass_tests", [])
    if not isinstance(must_pass, list):
        return False, "must_pass_tests must be a list"

    if not must_pass:
        return False, "must_pass_tests cannot be empty"

    return True, None


def test_file_status(test_file_path):
    """
    Check the status of a test file: 'PASSING', 'FAILING', or 'NOT_FOUND'.
    """
    if not test_file_path:
        return "NOT_FOUND"

    if not os.path.isfile(test_file_path):
        return "NOT_FOUND"

    try:
        result = subprocess.run(
            ["python", "-m", "pytest", test_file_path, "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        return "PASSING" if result.returncode == 0 else "FAILING"
    except Exception:
        return "FAILING"


def run_must_pass_tests(test_file_path, must_pass_tests):
    """
    Run specific must-pass tests from a test file.
    Returns dict: {
        "passed": [test_names that passed],
        "failed": [test_names that failed],
        "not_found": [test_names not found],
        "exit_code": int,
        "stdout": str,
        "stderr": str
    }
    """
    result = {
        "passed": [],
        "failed": [],
        "not_found": [],
        "exit_code": 1,
        "stdout": "",
        "stderr": ""
    }

    if not test_file_path or not os.path.isfile(test_file_path):
        result["not_found"] = list(must_pass_tests or [])
        return result

    if not must_pass_tests:
        return result

    test_args = [f"{test_file_path}::{t}" for t in must_pass_tests]

    try:
        proc = subprocess.run(
            ["python", "-m", "pytest"] + test_args + ["-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        result["exit_code"] = proc.returncode
        result["stdout"] = proc.stdout
        result["stderr"] = proc.stderr

        for test_name in must_pass_tests:
            test_marker = f"{os.path.basename(test_file_path)}::{test_name}"
            if f"PASSED" in proc.stdout and test_name in proc.stdout:
                result["passed"].append(test_name)
            elif f"FAILED" in proc.stdout and test_name in proc.stdout:
                result["failed"].append(test_name)
            else:
                result["not_found"].append(test_name)

        if not result["passed"] and not result["failed"]:
            result["not_found"] = list(must_pass_tests)

    except Exception as e:
        result["stderr"] = str(e)
        result["not_found"] = list(must_pass_tests or [])

    return result


def invalidate_cache():
    """Clear the TDD cache (used by tests and dynamic reloads)."""
    _TDD_CACHE["enabled"] = None
    _TDD_CACHE["kinds"] = None
    _TDD_CACHE["cached_at"] = 0.0
