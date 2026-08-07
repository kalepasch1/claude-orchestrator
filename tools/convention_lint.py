#!/usr/bin/env python3
"""
CLAUDE.md Convention Linter - Phase 1: Minimum Viable Linter

Detects violations of 3 core conventions:
1. Fail-soft error handling: Detect raise statements in public module-level functions
2. Hardcoded secrets in config keys: Flag string literals matching PASSWORD|TOKEN|SECRET|KEY=
3. Module-level singletons: Verify functions like acquire() exist before instance methods

Usage:
    python tools/convention_lint.py [--check-path=<dir>] [--json] [--fail-on=error]

Output:
    JSON: {"file": str, "line": int, "rule": str, "message": str, "severity": "error|warn"}
    Text: <file>:<line>: <rule>: <message>
"""
import ast
import json
import re
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import List, Dict, Optional, Any


#: A select window at or above this many rows is big enough that truncation is silent and
#: consequential. Below it the caller is visibly asking for a handful of rows.
SCAN_WINDOW_MIN_LIMIT = 100

#: Limits that are a deliberate "is there more than N?" probe rather than a data window.
#: fleet_stuck_alarm.py reads 5001 to answer "more than 5000?" — len() of that page IS the
#: answer, so it is exempt by design. Documented as the exception, not fixed.
SENTINEL_LIMITS = {5001}


class ConventionViolation:
    """Represents a single convention violation."""

    def __init__(self, filepath: str, lineno: int, rule: str, message: str, severity: str = "error"):
        self.filepath = filepath
        self.lineno = lineno
        self.rule = rule
        self.message = message
        self.severity = severity

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "file": self.filepath,
            "line": self.lineno,
            "rule": self.rule,
            "message": self.message,
            "severity": self.severity,
        }

    def __str__(self) -> str:
        return f"{self.filepath}:{self.lineno}: {self.rule}: {self.message}"


class ConventionChecker(ast.NodeVisitor):
    """AST visitor that checks Python files for convention violations."""

    def __init__(self, filepath: str, source_lines: List[str]):
        self.filepath = filepath
        self.source_lines = source_lines
        self.violations: List[ConventionViolation] = []
        self.function_context: List[str] = []
        self.class_depth = 0

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track class context to distinguish methods from module functions."""
        self.class_depth += 1
        self.generic_visit(node)
        self.class_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check function definitions for error handling violations."""
        self.function_context.append(node.name)
        self._check_fail_soft_error_handling(node)
        self.generic_visit(node)
        self.function_context.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Check async function definitions for error handling violations."""
        self.function_context.append(node.name)
        self._check_fail_soft_error_handling(node)
        self.generic_visit(node)
        self.function_context.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        """Check for hardcoded secrets in assignments."""
        self._check_hardcoded_secrets(node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Check db.select calls for the unbounded-scan-window shape."""
        self._check_scan_window(node)
        self.generic_visit(node)

    def _check_scan_window(self, node: ast.Call) -> None:
        """
        Rule 3: Unbounded client-side scan window

        Flag `select(..., {"limit": ">=100"})` with no `"order"` key. That exact shape has
        produced four outage-class failures on this fleet: merge_train._pick_cards (newest
        3,000 of 238,177 approvals -> months of stranded work), ensure_integration_card
        (240 duplicates of one slug), ev_scheduler._scored_queue (an arbitrary,
        non-reproducible 500 of 1,407 QUEUED tasks, so ~907 were invisible to EV ordering),
        and config_optimizer (a queue depth structurally incapable of exceeding 1,000
        driving parallelism decisions).

        Without an ORDER BY the window is not even the same rows twice, so the bug is both
        silent and unreproducible. A larger limit is the same bug, later — the fix is to
        classify the read (COUNT / LOOKUP / SAMPLE / FULL SCAN; see db.select_all) rather
        than to raise the number.
        """
        name = node.func.attr if isinstance(node.func, ast.Attribute) else (
            node.func.id if isinstance(node.func, ast.Name) else None)
        if name not in ("select", "select_all"):
            return
        if name == "select_all":
            return          # pages to exhaustion; a window is not possible

        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            if not isinstance(arg, ast.Dict):
                continue
            keys = {k.value for k in arg.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if "limit" not in keys:
                continue
            limit_val = None
            for k, v in zip(arg.keys, arg.values):
                if not (isinstance(k, ast.Constant) and k.value == "limit"):
                    continue
                # "limit": "500" | 500 | str(500)
                if isinstance(v, ast.Constant):
                    try:
                        limit_val = int(v.value)
                    except (TypeError, ValueError):
                        limit_val = None
                elif (isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
                        and v.func.id == "str" and v.args
                        and isinstance(v.args[0], ast.Constant)):
                    try:
                        limit_val = int(v.args[0].value)
                    except (TypeError, ValueError):
                        limit_val = None
            if limit_val is None or limit_val < SCAN_WINDOW_MIN_LIMIT:
                continue
            if limit_val in SENTINEL_LIMITS:
                # Deliberate "more than N" probe: fleet_stuck_alarm.py reads limit 5001
                # purely to answer "are there more than 5000?", and len() of that page is
                # the answer it wants. Legitimate idiom, not a window bug.
                continue
            if "order" in keys:
                continue
            self.violations.append(ConventionViolation(
                self.filepath, node.lineno, 'SCAN_WINDOW_NO_ORDER',
                f'select(..., limit={limit_val}) has no "order" — the window is '
                f'non-deterministic and silently truncates. Classify the read: COUNT -> '
                f'db.count(), LOOKUP -> filter server-side, SAMPLE -> add a deterministic '
                f'"order", FULL SCAN -> db.select_all(). Do not just raise the limit.',
                severity='warning'
            ))
            return

    def _check_fail_soft_error_handling(self, node: ast.FunctionDef) -> None:
        """
        Rule 1: Fail-soft error handling

        Public module-level functions should not raise on bad input.
        Flag functions that have raise statements but no try/except handlers.
        """
        # Only check public module-level functions
        if self.class_depth > 0 or node.name.startswith('_'):
            return

        has_raise = False
        for child in ast.walk(node):
            if isinstance(child, ast.Raise):
                has_raise = True
                break

        if has_raise:
            # Check if there are try/except blocks that handle errors gracefully
            has_error_handler = False
            for child in ast.walk(node):
                if isinstance(child, ast.Try):
                    for handler in child.handlers:
                        # Check if handler has a return statement (fail-soft)
                        has_return = any(isinstance(stmt, ast.Return) for stmt in handler.body)
                        if has_return:
                            has_error_handler = True
                            break

            if not has_error_handler:
                self.violations.append(ConventionViolation(
                    self.filepath, node.lineno, 'FAIL_SOFT_ERROR',
                    f'Public function "{node.name}" raises on bad input; use try/except with sensible defaults instead'
                ))

    def _check_hardcoded_secrets(self, node: ast.Assign) -> None:
        """
        Rule 2: Hardcoded secrets in config keys

        Flag string literals that look like secrets (PASSWORD|TOKEN|SECRET|KEY=).
        """
        secret_patterns = [
            r'PASSWORD', r'TOKEN', r'SECRET', r'API_KEY', r'PRIVATE_KEY',
            r'AUTH', r'CREDENTIAL', r'KEY='
        ]
        secret_regex = re.compile('|'.join(secret_patterns), re.IGNORECASE)

        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            value = node.value.value
            # Skip environment variable placeholders like $SECRET or ${SECRET}
            if value.startswith('$'):
                return

            for target in node.targets:
                if isinstance(target, ast.Name):
                    var_name = target.id
                    if secret_regex.search(var_name):
                        self.violations.append(ConventionViolation(
                            self.filepath, node.lineno, 'HARDCODED_SECRET',
                            f'Variable "{var_name}" contains secret keyword; use environment variables instead'
                        ))
                elif isinstance(target, ast.Subscript):
                    if isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str):
                        key_name = target.slice.value
                        if secret_regex.search(key_name):
                            self.violations.append(ConventionViolation(
                                self.filepath, node.lineno, 'HARDCODED_SECRET',
                                f'Config key "{key_name}" contains secret keyword; use environment variables instead'
                            ))


_NOQA_RE = re.compile(r'#\s*noqa\b(?:\s*:\s*(?P<rules>[A-Z0-9_,\s]+))?')


def _apply_noqa(violations: List[ConventionViolation],
                source_lines: List[str]) -> List[ConventionViolation]:
    """Honour `# noqa: RULE_NAME` (and bare `# noqa`) on the offending line.

    CONVENTION_LINT.md has documented this escape hatch since Phase 1 but nothing
    implemented it, so the documented way to accept a deliberate exception did not work
    and the only way to silence a rule was to stop running the linter.
    """
    kept = []
    for v in violations:
        line = source_lines[v.lineno - 1] if 0 < v.lineno <= len(source_lines) else ''
        m = _NOQA_RE.search(line)
        if m:
            rules = m.group('rules')
            if not rules:
                continue                                  # bare noqa suppresses all
            if v.rule in {r.strip() for r in rules.split(',') if r.strip()}:
                continue
        kept.append(v)
    return kept


def check_file(filepath: str) -> List[ConventionViolation]:
    """Parse and check a Python file for convention violations."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()
        source_lines = source.split('\n')
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return [ConventionViolation(
                filepath, e.lineno or 1, 'SYNTAX_ERROR',
                f'Syntax error: {e.msg}'
            )]

        checker = ConventionChecker(filepath, source_lines)
        checker.visit(tree)
        return _apply_noqa(checker.violations, source_lines)
    except Exception as e:
        return [ConventionViolation(
            filepath, 1, 'CHECK_ERROR',
            f'Error checking file: {str(e)}'
        )]


def check_directory(directory: str) -> List[ConventionViolation]:
    """Check all Python files in a directory."""
    violations = []
    path = Path(directory)

    for py_file in path.rglob('*.py'):
        # Skip common directories
        if any(part in py_file.parts for part in ['.git', '__pycache__', '.pytest_cache', 'node_modules']):
            continue
        violations.extend(check_file(str(py_file)))

    return violations


def main() -> int:
    """Main entry point."""
    parser = ArgumentParser(description='CLAUDE.md Convention Linter')
    parser.add_argument('paths', nargs='*', default=['runner', 'tools'],
                        help='Files or directories to check (default: runner, tools)')
    parser.add_argument('--check-path', dest='check_paths', action='append',
                        help='Additional paths to check (can be repeated)')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON')
    parser.add_argument('--fail-on', choices=['error', 'warn'], default='error',
                        help='Severity level that causes non-zero exit (default: error)')

    args = parser.parse_args()

    # Collect all paths to check
    check_paths = args.paths or ['runner', 'tools']
    if args.check_paths:
        check_paths.extend(args.check_paths)

    # Run linter on all paths
    all_violations = []
    for path in check_paths:
        if Path(path).is_dir():
            all_violations.extend(check_directory(path))
        elif Path(path).is_file():
            all_violations.extend(check_file(path))

    # Output results
    if args.json:
        output = [v.to_dict() for v in all_violations]
        print(json.dumps(output, indent=2))
    else:
        for violation in sorted(all_violations, key=lambda v: (v.filepath, v.lineno)):
            print(str(violation))

    # Determine exit code
    if all_violations:
        error_violations = [v for v in all_violations if v.severity == 'error']
        if error_violations and args.fail_on == 'error':
            return 1
        if all_violations and args.fail_on == 'warn':
            return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
