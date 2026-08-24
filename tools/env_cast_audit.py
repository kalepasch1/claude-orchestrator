"""Audit module-scope environment casts that can wedge an import.

WHY
---
`MAX = int(os.environ.get("ORCH_MAX", "8"))` at module scope is evaluated at *import*
time. If a fleet push sets ORCH_MAX to anything unparseable, the cast raises ValueError
while the module is being imported, so every importer of that module dies too — not
just the code that reads MAX. Config that is supposed to be pushable becomes config
that can brick the fleet.

`runner/config_consumer.py` exposes fail-soft equivalents (`env_int`, `env_float`,
`env_bool`, `env_str`) that log the bad value and fall back to the declared default.
This tool finds the call sites still using a bare cast, so the migration is measurable
instead of vibes-based.

Only *module-scope* casts are reported. The same expression inside a function is
evaluated when called, where a normal try/except can contain it, so it cannot take an
import down.

Usage::

    python -m tools.env_cast_audit                 # human summary
    python -m tools.env_cast_audit --json          # machine-readable
    python -m tools.env_cast_audit --paths runner tools
    python -m tools.env_cast_audit --max-allowed 900   # exit 1 above the ratchet

Fail-soft: an unparseable file is skipped, never fatal.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from typing import Any, Dict, Iterable, List, Optional

__all__ = ["find_module_scope_env_casts", "audit_paths", "main"]

CAST_NAMES = frozenset({"int", "float", "bool"})
ENV_TOKENS = ("os.environ", "environ.get", "getenv")

DEFAULT_PATHS = ("runner", "tools")


def _reads_env(node: ast.AST) -> bool:
    try:
        source = ast.unparse(node)
    except Exception:
        return False
    return any(token in source for token in ENV_TOKENS)


def find_module_scope_env_casts(source: str, filename: str = "<unknown>") -> List[Dict[str, Any]]:
    """Return every bare env cast evaluated at import time in ``source``.

    Returns ``[]`` on unparseable input rather than raising.
    """
    try:
        tree = ast.parse(source, filename=filename)
    except Exception:
        return []

    findings: List[Dict[str, Any]] = []
    for statement in tree.body:
        # Only top-level assignments run unconditionally at import. A cast inside a
        # module-level `if`/`try` is still import-time, so those are walked too.
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for node in ast.walk(statement):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Name) and node.func.id in CAST_NAMES):
                continue
            if not _reads_env(node):
                continue
            try:
                expression = ast.unparse(node)
            except Exception:
                expression = f"{node.func.id}(...)"
            findings.append({
                "file": filename,
                "line": getattr(node, "lineno", getattr(statement, "lineno", 0)),
                "cast": node.func.id,
                "expression": expression[:160],
                "suggestion": f"config_consumer.env_{node.func.id}(...)",
            })
    return findings


def _python_files(paths: Iterable[str], root: str) -> List[str]:
    collected: List[str] = []
    for entry in paths:
        target = entry if os.path.isabs(entry) else os.path.join(root, entry)
        if os.path.isfile(target) and target.endswith(".py"):
            collected.append(target)
            continue
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames
                           if d not in {"__pycache__", "_to_delete", ".git", "node_modules"}]
            collected.extend(os.path.join(dirpath, f)
                             for f in filenames if f.endswith(".py"))
    return sorted(collected)


def audit_paths(paths: Optional[Iterable[str]] = None, root: str = ".") -> List[Dict[str, Any]]:
    """Audit ``paths`` (default: runner, tools). Never raises."""
    try:
        files = _python_files(paths or DEFAULT_PATHS, root)
    except Exception:
        return []
    findings: List[Dict[str, Any]] = []
    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                source = handle.read()
        except Exception:
            continue
        relative = os.path.relpath(path, root)
        findings.extend(find_module_scope_env_casts(source, relative))
    return findings


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--paths", nargs="*", default=list(DEFAULT_PATHS))
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-allowed", type=int, default=None,
                        help="exit 1 when the finding count exceeds this ratchet")
    parser.add_argument("--limit", type=int, default=40, help="rows to print")
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit:
        return 0

    findings = audit_paths(args.paths, args.root)

    if args.json:
        print(json.dumps({"count": len(findings), "findings": findings}, indent=2))
    else:
        by_file: Dict[str, int] = {}
        for item in findings:
            by_file[item["file"]] = by_file.get(item["file"], 0) + 1
        print(f"{len(findings)} import-time env cast(s) across {len(by_file)} file(s)")
        print("Replace with config_consumer.env_int / env_float / env_bool / env_str.\n")
        for item in findings[:max(args.limit, 0)]:
            print(f"{item['file']}:{item['line']}: {item['expression']}")
        if len(findings) > args.limit:
            print(f"... {len(findings) - args.limit} more (use --json for all)")

    if args.max_allowed is not None and len(findings) > args.max_allowed:
        print(f"\nFAIL: {len(findings)} exceeds the ratchet of {args.max_allowed}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
