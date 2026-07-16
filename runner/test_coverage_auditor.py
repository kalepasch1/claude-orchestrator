"""Test coverage auditor for CI/CD pipeline.

Analyzes recent code changes to identify functions lacking test coverage.
"""
import os
import re
import logging
from typing import Dict, List, Any

log = logging.getLogger(__name__)

def find_python_functions(file_path: str) -> List[Dict[str, Any]]:
    functions = []
    try:
        with open(file_path, "r") as f:
            for i, line in enumerate(f, 1):
                m = re.match(r"^(    )?def (\w+)\(", line)
                if m:
                    functions.append({
                        "name": m.group(2),
                        "line": i,
                        "is_method": bool(m.group(1)),
                        "file": file_path,
                    })
    except (OSError, UnicodeDecodeError):
        pass
    return functions

def find_test_files(repo_path: str) -> List[str]:
    test_files = []
    for root, _, files in os.walk(repo_path):
        for f in files:
            if f.startswith("test_") and f.endswith(".py"):
                test_files.append(os.path.join(root, f))
    return test_files

def has_test_coverage(func_name: str, test_files: List[str]) -> bool:
    pattern = re.compile(rf"\b{re.escape(func_name)}\b")
    for tf in test_files:
        try:
            with open(tf, "r") as f:
                if pattern.search(f.read()):
                    return True
        except (OSError, UnicodeDecodeError):
            continue
    return False

def audit_coverage(repo_path: str, subdir: str = "runner") -> Dict[str, Any]:
    scan_dir = os.path.join(repo_path, subdir)
    test_files = find_test_files(repo_path)
    all_funcs = []
    covered = []
    uncovered = []
    if not os.path.isdir(scan_dir):
        return {"total": 0, "covered": 0, "uncovered": 0, "details": []}
    for root, _, files in os.walk(scan_dir):
        if "test" in root:
            continue
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            funcs = find_python_functions(fpath)
            for fn in funcs:
                if fn["name"].startswith("_"):
                    continue
                all_funcs.append(fn)
                if has_test_coverage(fn["name"], test_files):
                    covered.append(fn)
                else:
                    uncovered.append(fn)
    return {
        "total": len(all_funcs),
        "covered": len(covered),
        "uncovered": len(uncovered),
        "coverage_pct": round(len(covered) / max(len(all_funcs), 1) * 100, 1),
        "uncovered_details": [{"name": f["name"], "file": f["file"], "line": f["line"]} for f in uncovered[:20]],
    }
