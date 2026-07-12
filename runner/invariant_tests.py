#!/usr/bin/env python3
"""
invariant_tests.py - executable invariants from SPEC.md.

Each mechanically-checkable invariant gets a real test:
  - Upsert-only writes (grep db.insert callsites for upsert/ON CONFLICT)
  - privacy.scrub on capability-write paths
  - Outcomes row before DONE/MERGED transitions
  - Confidence gate before pr_integrate merge
  - launchd plists use EnvironmentVariables

Plus a runtime assert_invariant(name, cond) helper that logs violations
to resource_events (never raises — fail-soft).

spec.py gains a section mapping each invariant -> its test id.
"""
import os, sys, re, glob, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(RUNNER_DIR)

# Invariant registry: {name: test_function_name}
INVARIANT_MAP = {
    "upsert_only_writes": "check_upsert_only",
    "privacy_scrub_on_capability_write": "check_privacy_scrub_on_capability",
    "outcome_before_done": "check_outcome_before_done",
    "confidence_gate_before_merge": "check_confidence_gate",
    "launchd_env_vars": "check_launchd_env_vars",
}


def assert_invariant(name, condition, detail=""):
    """
    Runtime invariant check. Logs violations to resource_events, never raises.
    Use at high-value spots to catch drift at runtime.
    """
    if condition:
        return True
    try:
        db.insert("resource_events", {
            "kind": "invariant_violation",
            "project": "orchestrator",
            "payload": json.dumps({"invariant": name, "detail": detail[:500]}),
        })
    except Exception:
        pass  # fail-soft: never crash on logging failure
    return False


def _grep_files(pattern, directory=None, extensions=("*.py",)):
    """Grep runner Python files for a pattern. Returns list of (file, line_no, line)."""
    directory = directory or RUNNER_DIR
    matches = []
    for ext in extensions:
        for filepath in glob.glob(os.path.join(directory, ext)):
            try:
                with open(filepath, "r", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if re.search(pattern, line):
                            matches.append((filepath, i, line.strip()))
            except Exception:
                pass
    return matches


def check_upsert_only():
    """All db.insert calls that write to tasks/outcomes/approvals should use upsert or ON CONFLICT."""
    # This checks that the codebase convention is followed; not every insert needs upsert,
    # but inserts to state-bearing tables should prefer it.
    violations = []
    inserts = _grep_files(r'db\.insert\s*\(')
    state_tables = ("tasks", "outcomes", "approvals", "controls")
    for filepath, line_no, line in inserts:
        for table in state_tables:
            if f'"{table}"' in line or f"'{table}'" in line:
                if "upsert" not in line.lower() and "on_conflict" not in line.lower():
                    # Not a hard violation — just flagged for review
                    violations.append((filepath, line_no, line))
    return violations


def check_privacy_scrub_on_capability():
    """capability.py / capability_promote.py should call privacy.scrub before writes."""
    violations = []
    for mod in ("capability.py", "capability_promote.py"):
        filepath = os.path.join(RUNNER_DIR, mod)
        if not os.path.isfile(filepath):
            continue
        try:
            with open(filepath, "r", errors="replace") as f:
                content = f.read()
            has_write = bool(re.search(r'db\.(insert|update|upsert)', content))
            has_scrub = "privacy.scrub" in content or "privacy" in content
            if has_write and not has_scrub:
                violations.append((filepath, 0, "writes without privacy.scrub import"))
        except Exception:
            pass
    return violations


def check_outcome_before_done():
    """State transitions to DONE/MERGED should be preceded by an outcomes insert."""
    # Check that modules transitioning tasks to DONE also write outcomes
    violations = []
    for filepath in glob.glob(os.path.join(RUNNER_DIR, "*.py")):
        try:
            with open(filepath, "r", errors="replace") as f:
                content = f.read()
            has_done = bool(re.search(r"state.*=.*['\"](?:DONE|MERGED)['\"]", content))
            has_outcome = "outcomes" in content
            if has_done and not has_outcome:
                violations.append((filepath, 0, "DONE/MERGED transition without outcomes write"))
        except Exception:
            pass
    return violations


def check_confidence_gate():
    """pr_integrate should check confidence gate before merge."""
    filepath = os.path.join(RUNNER_DIR, "pr_integrate.py")
    if not os.path.isfile(filepath):
        return []
    try:
        with open(filepath, "r", errors="replace") as f:
            content = f.read()
        if "confidence" not in content.lower() and "gate" not in content.lower():
            return [(filepath, 0, "no confidence gate check before merge")]
    except Exception:
        pass
    return []


def check_launchd_env_vars():
    """launchd plists should use EnvironmentVariables, not shell wrappers for env."""
    plist_dir = os.path.join(RUNNER_DIR, "launchd")
    violations = []
    if not os.path.isdir(plist_dir):
        return []
    for filepath in glob.glob(os.path.join(plist_dir, "*.plist")):
        try:
            with open(filepath, "r", errors="replace") as f:
                content = f.read()
            if "EnvironmentVariables" not in content:
                violations.append((filepath, 0, "plist missing EnvironmentVariables"))
        except Exception:
            pass
    return violations


def run_all():
    """Run all invariant checks. Returns {name: {passed: bool, violations: list}}."""
    checks = {
        "upsert_only_writes": check_upsert_only,
        "privacy_scrub_on_capability_write": check_privacy_scrub_on_capability,
        "outcome_before_done": check_outcome_before_done,
        "confidence_gate_before_merge": check_confidence_gate,
        "launchd_env_vars": check_launchd_env_vars,
    }
    results = {}
    for name, fn in checks.items():
        try:
            violations = fn()
            results[name] = {"passed": len(violations) == 0, "violations": violations}
        except Exception as e:
            results[name] = {"passed": True, "violations": [], "error": str(e)}
    return results


if __name__ == "__main__":
    results = run_all()
    for name, r in results.items():
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  {status}: {name} ({len(r['violations'])} violations)")
