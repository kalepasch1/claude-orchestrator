#!/usr/bin/env python3
"""
test_coverage_analyzer.py – AI-driven test-coverage analysis for runner modules.

Scans runner/ for Python modules and their corresponding test files, identifies
coverage gaps (modules without tests, modules with low test-to-code ratio),
and generates a prioritized report of where new tests would have the most impact.

Follows project conventions:
- Module-level singleton via _STATE
- Fail-soft: returns partial results on errors
- Env-var config with ORCH_ prefix
- Thread-safe with explicit lock
"""
import os, sys, re, json, ast, threading, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
MIN_TEST_RATIO = float(os.environ.get("ORCH_MIN_TEST_RATIO", "0.3"))
CRITICAL_MODULES = os.environ.get(
    "ORCH_CRITICAL_MODULES",
    "db,fleet_config,build_gate,quarantine,branch_lifecycle"
).split(",")

_lock = threading.Lock()
_STATE = {
    "last_scan": None,
    "gaps": [],
    "stats": {},
}


def _list_modules():
    """Return list of runner/*.py module names (excluding tests and __init__)."""
    modules = []
    try:
        for f in os.listdir(RUNNER_DIR):
            if (f.endswith(".py")
                    and not f.startswith("test_")
                    and not f.startswith("__")
                    and f != "conftest.py"):
                modules.append(f[:-3])
    except OSError:
        pass
    return sorted(modules)


def _list_test_files():
    """Return dict mapping module_name -> list of test file paths."""
    test_map = {}
    try:
        for f in os.listdir(RUNNER_DIR):
            if f.startswith("test_") and f.endswith(".py"):
                # test_foo_bar.py -> try to match foo_bar module
                mod_name = f[5:-3]  # strip test_ prefix and .py suffix
                test_map.setdefault(mod_name, []).append(
                    os.path.join(RUNNER_DIR, f)
                )
    except OSError:
        pass
    return test_map


def _count_functions(filepath):
    """Count public functions/classes in a Python file using AST."""
    try:
        with open(filepath, "r") as fh:
            tree = ast.parse(fh.read(), filename=filepath)
    except (SyntaxError, OSError, UnicodeDecodeError):
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                count += 1
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                count += 1
    return count


def _count_test_cases(filepath):
    """Count test functions (def test_*) in a test file."""
    try:
        with open(filepath, "r") as fh:
            tree = ast.parse(fh.read(), filename=filepath)
    except (SyntaxError, OSError, UnicodeDecodeError):
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                count += 1
    return count


def _line_count(filepath):
    """Count non-blank, non-comment lines."""
    try:
        with open(filepath, "r") as fh:
            lines = fh.readlines()
    except OSError:
        return 0
    return sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))


def analyze():
    """
    Scan runner/ and return a coverage analysis report.

    Returns dict with:
      - total_modules: int
      - tested_modules: int
      - untested_modules: list of module names
      - coverage_ratio: float (0-1)
      - gaps: list of {module, public_fns, test_cases, ratio, priority}
      - critical_untested: list of critical modules without tests
    """
    modules = _list_modules()
    test_map = _list_test_files()

    gaps = []
    tested = 0
    untested_names = []

    for mod in modules:
        mod_path = os.path.join(RUNNER_DIR, mod + ".py")
        pub_fns = _count_functions(mod_path)
        mod_lines = _line_count(mod_path)

        test_files = test_map.get(mod, [])
        total_tests = sum(_count_test_cases(tf) for tf in test_files)
        total_test_lines = sum(_line_count(tf) for tf in test_files)

        if total_tests > 0:
            tested += 1
        else:
            untested_names.append(mod)

        ratio = total_tests / max(pub_fns, 1)
        is_critical = mod in CRITICAL_MODULES

        # Priority scoring: higher = more urgent need for tests
        priority = 0
        if total_tests == 0:
            priority += 50
        if is_critical:
            priority += 30
        if ratio < MIN_TEST_RATIO:
            priority += 20
        priority += min(pub_fns, 20)  # more public API = more need

        gaps.append({
            "module": mod,
            "lines": mod_lines,
            "public_fns": pub_fns,
            "test_cases": total_tests,
            "test_lines": total_test_lines,
            "ratio": round(ratio, 2),
            "is_critical": is_critical,
            "priority": priority,
        })

    gaps.sort(key=lambda g: g["priority"], reverse=True)

    critical_untested = [m for m in untested_names if m in CRITICAL_MODULES]
    coverage_ratio = tested / max(len(modules), 1)

    result = {
        "total_modules": len(modules),
        "tested_modules": tested,
        "untested_modules": untested_names,
        "coverage_ratio": round(coverage_ratio, 3),
        "gaps": gaps,
        "critical_untested": critical_untested,
        "scanned_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

    with _lock:
        _STATE["last_scan"] = result["scanned_at"]
        _STATE["gaps"] = gaps[:10]
        _STATE["stats"] = {
            "total": len(modules),
            "tested": tested,
            "ratio": coverage_ratio,
        }

    return result


def suggest_tests(module_name):
    """
    For a given module, suggest test cases based on its public API.

    Returns list of suggested test function names with docstrings.
    """
    mod_path = os.path.join(RUNNER_DIR, module_name + ".py")
    if not os.path.exists(mod_path):
        return {"error": f"module {module_name} not found"}

    try:
        with open(mod_path, "r") as fh:
            tree = ast.parse(fh.read(), filename=mod_path)
    except (SyntaxError, OSError):
        return {"error": f"could not parse {module_name}"}

    suggestions = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            fn_name = node.name
            # Generate test suggestions based on function signature
            args = [a.arg for a in node.args.args if a.arg != "self"]

            cases = [
                f"test_{fn_name}_returns_expected",
                f"test_{fn_name}_handles_empty_input",
            ]
            if any(kw in fn_name for kw in ("get", "fetch", "select", "read")):
                cases.append(f"test_{fn_name}_not_found_returns_none")
            if any(kw in fn_name for kw in ("insert", "update", "write", "create")):
                cases.append(f"test_{fn_name}_validates_input")
            if args:
                cases.append(f"test_{fn_name}_with_none_args")

            suggestions.append({
                "function": fn_name,
                "args": args,
                "suggested_tests": cases,
            })

    return {
        "module": module_name,
        "suggestions": suggestions,
        "count": sum(len(s["suggested_tests"]) for s in suggestions),
    }


def coverage_report():
    """Generate a human-readable coverage report string."""
    data = analyze()
    lines = [
        f"# Test Coverage Report — {data['scanned_at']}",
        f"",
        f"Modules: {data['tested_modules']}/{data['total_modules']} tested "
        f"({data['coverage_ratio']*100:.1f}%)",
        f"",
    ]

    if data["critical_untested"]:
        lines.append("## Critical modules without tests")
        for m in data["critical_untested"]:
            lines.append(f"  - {m}")
        lines.append("")

    lines.append("## Top priority gaps")
    for g in data["gaps"][:15]:
        flag = " [CRITICAL]" if g["is_critical"] else ""
        lines.append(
            f"  {g['module']}: {g['test_cases']} tests / "
            f"{g['public_fns']} fns (ratio={g['ratio']}){flag}"
        )

    return "\n".join(lines)


def stats():
    """Return last cached stats without re-scanning."""
    with _lock:
        return dict(_STATE)


def run():
    """Entry point for orchestrator periodic jobs."""
    report = analyze()
    try:
        import db
        db.insert("inbox", {
            "kind": "test_coverage",
            "title": f"Test coverage: {report['coverage_ratio']*100:.0f}% "
                     f"({report['tested_modules']}/{report['total_modules']})",
            "body": coverage_report()[:3000],
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        })
    except Exception:
        pass  # fail-soft: inbox write is best-effort
    return report


if __name__ == "__main__":
    print(coverage_report())
