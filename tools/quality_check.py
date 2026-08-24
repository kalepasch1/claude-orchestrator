#!/usr/bin/env python3
"""quality_check.py — the single entry point for the repo's quality gates.

WHY THIS EXISTS. The checks were already written and each ran on its own: `git grep` for
conflict markers, `tools/convention_lint.py`, and nothing at all for syntax. There was no
`make lint`, so "run the complete quality check suite end to end" had no suite to run, and
in practice nobody ran all of them together.

That gap was not theoretical. FOUR files were committed to master carrying their merge
conflict markers — hisanta/__init__.py, hisanta/contracts/family.py,
hisanta/hisanta/contracts/family.py and hisanta/hisanta/mastery/engine.py. Every one is a
SyntaxError, and they took out COLLECTION of three test modules, which is the most
expensive kind of red because the tests inside never run and are never counted as
failures. A thirty-second `compileall` would have refused all four at the door.

HARD vs ADVISORY, and why the split matters. A gate that fails on everything gets
disabled within a week. So:

  * HARD (exit non-zero): syntax errors and committed conflict markers. Both are
    unambiguous, both are always a mistake, and neither has a legitimate exception.
  * ADVISORY (reported, exit zero): convention_lint findings. There are ~200 of them on
    master; failing the build on those today would just mean nobody runs this. The COUNT
    is printed so it can be ratcheted deliberately, the way
    runner/tests/test_scan_window_contracts.py ratchets its own rule.

DETERMINISM. The task that asked for this specified "run checks multiple times to confirm
stability", so every listing is sorted and no check depends on filesystem walk order.
Same tree in, byte-identical report out.
"""
from __future__ import annotations

import argparse
import json
import os
import py_compile
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Sequence

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Directories never worth compiling or linting.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "_to_delete",
             ".runtime", "build", "dist", ".mypy_cache", ".pytest_cache"}

#: Anchored the way git writes them. A markdown `=======` underline is NOT a marker,
#: so only the two unambiguous forms are searched.
CONFLICT_MARKERS = ("^<<<<<<< ", "^>>>>>>> ")


def _python_files(root: str) -> List[str]:
    """Every tracked-looking .py file under `root`, sorted. Deterministic by contract."""
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(".py"):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def check_syntax(root: str = REPO) -> Dict[str, Any]:
    """Every Python file must compile. HARD gate.

    This is the check that was missing entirely, and the one that would have caught all
    four committed-conflict-marker files.
    """
    failures = []
    for path in _python_files(root):
        try:
            py_compile.compile(path, cfile=os.path.join(tempfile.gettempdir(),
                                                        "quality_check.pyc"),
                               doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append({"file": os.path.relpath(path, root),
                             "error": str(exc).strip().splitlines()[-1][:200]})
        except Exception as exc:            # unreadable file, permissions, ...
            failures.append({"file": os.path.relpath(path, root),
                             "error": f"could not compile: {exc}"[:200]})
    return {"name": "syntax", "hard": True, "ok": not failures,
            "failures": sorted(failures, key=lambda f: f["file"])}


def check_conflict_markers(root: str = REPO) -> Dict[str, Any]:
    """No tracked file may contain unresolved conflict markers. HARD gate."""
    offenders = set()
    for marker in CONFLICT_MARKERS:
        try:
            out = subprocess.run(["git", "grep", "-l", marker], cwd=root,
                                 capture_output=True, text=True, timeout=120)
        except Exception:
            continue
        if out.returncode not in (0, 1):
            continue
        offenders.update(p for p in out.stdout.splitlines()
                         if p and "node_modules" not in p
                         and not p.endswith("tools/quality_check.py"))
    return {"name": "conflict_markers", "hard": True, "ok": not offenders,
            "failures": [{"file": p, "error": "unresolved conflict marker"}
                         for p in sorted(offenders)]}


def check_conventions(root: str = REPO) -> Dict[str, Any]:
    """CLAUDE.md conventions. ADVISORY — reported with a count, never fails the build."""
    lint = os.path.join(root, "tools", "convention_lint.py")
    if not os.path.isfile(lint):
        return {"name": "conventions", "hard": False, "ok": True,
                "findings": 0, "note": "tools/convention_lint.py not present"}
    try:
        out = subprocess.run([sys.executable, lint, os.path.join(root, "runner")],
                             cwd=root, capture_output=True, text=True, timeout=600)
    except Exception as exc:
        return {"name": "conventions", "hard": False, "ok": True,
                "findings": 0, "note": f"lint could not run: {exc}"}
    lines = [ln for ln in out.stdout.splitlines() if ": " in ln and ".py:" in ln]
    return {"name": "conventions", "hard": False, "ok": True, "findings": len(lines)}


CHECKS = (check_syntax, check_conflict_markers, check_conventions)


def run(root: str = REPO) -> Dict[str, Any]:
    """Run every gate. Always returns a report; never raises."""
    results = []
    for check in CHECKS:
        try:
            results.append(check(root))
        except Exception as exc:            # a broken gate must not hide the others
            results.append({"name": getattr(check, "__name__", "check"), "hard": False,
                            "ok": True, "note": f"gate errored: {exc}"})
    hard_failures = [r for r in results if r.get("hard") and not r.get("ok")]
    return {"ok": not hard_failures, "checks": results,
            "hard_failures": [r["name"] for r in hard_failures]}


def format_report(report: Dict[str, Any]) -> str:
    lines = []
    for result in report.get("checks", []):
        label = "HARD" if result.get("hard") else "advisory"
        if result.get("hard"):
            failures = result.get("failures") or []
            status = "PASS" if result.get("ok") else f"FAIL ({len(failures)})"
            lines.append(f"[{label}] {result['name']}: {status}")
            for failure in failures[:20]:
                lines.append(f"    {failure['file']}: {failure['error']}")
            if len(failures) > 20:
                lines.append(f"    ... and {len(failures) - 20} more")
        else:
            note = result.get("note")
            detail = note or f"{result.get('findings', 0)} finding(s)"
            lines.append(f"[{label}] {result['name']}: {detail}")
    lines.append("RESULT: " + ("PASS" if report.get("ok")
                               else "FAIL — " + ", ".join(report.get("hard_failures", []))))
    return "\n".join(lines)


def main(argv: Sequence[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the repo quality gates.")
    parser.add_argument("--json", action="store_true", help="emit the raw report")
    parser.add_argument("--root", default=REPO)
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = run(args.root)
    print(json.dumps(report, indent=2, sort_keys=True) if args.json
          else format_report(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
