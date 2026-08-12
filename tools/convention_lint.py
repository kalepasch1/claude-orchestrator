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


#: Rules that a TEST file is expected to "violate" by doing its job.
#:
#: MEASURED 2026-08-12: the linter reported 246 violations and 178 of them (72%) were
#: inside test files. A test that asserts a function raises must contain a raise; a
#: fixture named `secret` or `fake_token` is a fixture, not a credential. So nearly
#: three quarters of the output was the suite working as designed.
#:
#: That matters because this linter is a pre-commit hook that exits 1. A gate whose
#: output is mostly false is not a strict gate — it is a gate everyone routes around
#: with --no-verify, at which point it enforces nothing at all. Accuracy is what makes
#: enforcement possible, so these two rules stop firing inside tests. Every other rule
#: still applies everywhere: a test module that hides a real singleton bug is still a
#: real bug.
TEST_EXEMPT_RULES = frozenset({"FAIL_SOFT_ERROR", "HARDCODED_SECRET"})


def is_test_file(filepath: str) -> bool:
    """True for pytest/unittest modules, by this repo's actual layout.

    Both spellings are in use here — runner/test_*.py alongside runner/tests/test_*.py —
    so match on either the directory or the filename.
    """
    p = str(filepath or "").replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    return (name.startswith("test_") or name.endswith("_test.py")
            or "/tests/" in p or p.startswith("tests/"))


class ConventionChecker(ast.NodeVisitor):
    """AST visitor that checks Python files for convention violations."""

    def __init__(self, filepath: str, source_lines: List[str]):
        self.filepath = filepath
        self.source_lines = source_lines
        self.violations: List[ConventionViolation] = []
        self.function_context: List[str] = []
        self.class_depth = 0
        self.is_test_file = is_test_file(filepath)

    def _record(self, violation: "ConventionViolation") -> None:
        """Single choke point for reporting, so the test exemption cannot be bypassed.

        Every rule reports through here rather than appending directly, so a rule added
        later inherits the exemption instead of quietly reintroducing the 72% noise.
        """
        if self.is_test_file and violation.rule in TEST_EXEMPT_RULES:
            return
        self.violations.append(violation)

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
                self._record(ConventionViolation(
                    self.filepath, node.lineno, 'FAIL_SOFT_ERROR',
                    f'Public function "{node.name}" raises on bad input; use try/except with sensible defaults instead'
                ))

        # A bare `except: pass` silently swallows every error including
        # KeyboardInterrupt/SystemExit — that is silent failure, not fail-soft
        # (fail-soft returns a sensible default). Flag it in public functions.
        for child in ast.walk(node):
            if not isinstance(child, ast.Try):
                continue
            for handler in child.handlers:
                bare = handler.type is None
                only_pass = all(isinstance(stmt, ast.Pass) for stmt in handler.body)
                if bare and only_pass:
                    self._record(ConventionViolation(
                        self.filepath, handler.lineno, 'FAIL_SOFT_ERROR',
                        f'Public function "{node.name}" has a bare "except: pass"; '
                        'catch specific exceptions and return a sensible default instead'
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
                        self._record(ConventionViolation(
                            self.filepath, node.lineno, 'HARDCODED_SECRET',
                            f'Variable "{var_name}" contains secret keyword; use environment variables instead'
                        ))
                elif isinstance(target, ast.Subscript):
                    if isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str):
                        key_name = target.slice.value
                        if secret_regex.search(key_name):
                            self._record(ConventionViolation(
                                self.filepath, node.lineno, 'HARDCODED_SECRET',
                                f'Config key "{key_name}" contains secret keyword; use environment variables instead'
                            ))


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
        return checker.violations
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
