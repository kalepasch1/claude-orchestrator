#!/usr/bin/env python3
"""
CLAUDE.md Convention Linter - Phase 1: Minimum Viable Linter

Detects violations of 3 core conventions:
1. Fail-soft error handling: Detect raise statements in public module-level functions
2. Hardcoded secrets in config keys: Flag string literals matching PASSWORD|TOKEN|SECRET|KEY=
3. Module-level singletons: Verify functions like acquire() exist before instance methods

Usage:
    python tools/convention_lint.py [files...] [--check-path=<dir>] [--json] [--fail-on=error]

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
from typing import List, Dict, Optional, Any, Set


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
        return f"{self.filepath}:{self.lineno}: [{self.rule}] {self.message}"


class ConventionChecker(ast.NodeVisitor):
    """AST visitor that checks Python files for convention violations."""

    def __init__(self, filepath: str, source_lines: List[str]):
        self.filepath = filepath
        self.source_lines = source_lines
        self.violations: List[ConventionViolation] = []
        self.function_context: List[str] = []
        self.class_depth = 0
        self.noqa_lines = self._parse_noqa_comments()

    def _parse_noqa_comments(self) -> Dict[int, Set[str]]:
        """Parse # noqa: RULE_NAME comments from source."""
        noqa_map: Dict[int, Set[str]] = {}
        noqa_pattern = re.compile(r'#\s*noqa:\s*([A-Z_]+)')
        for lineno, line in enumerate(self.source_lines, start=1):
            matches = noqa_pattern.findall(line)
            if matches:
                noqa_map[lineno] = set(matches)
        return noqa_map

    def _is_rule_disabled(self, lineno: int, rule: str) -> bool:
        """Check if a rule is disabled on a specific line."""
        return rule in self.noqa_lines.get(lineno, set())

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track class context to distinguish methods from module functions."""
        self.class_depth += 1
        self.generic_visit(node)
        self.class_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check function definitions for error handling violations."""
        self.function_context.append(node.name)
        self._check_fail_soft_error_handling(node)
        self._check_module_singletons(node)
        self.generic_visit(node)
        self.function_context.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Check async function definitions for error handling violations."""
        self.function_context.append(node.name)
        self._check_fail_soft_error_handling(node)
        self._check_module_singletons(node)
        self.generic_visit(node)
        self.function_context.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        """Check for hardcoded secrets in assignments."""
        self._check_hardcoded_secrets(node)
        self.generic_visit(node)

    def _has_try_except_with_return(self, node: ast.FunctionDef) -> bool:
        """Check if function has try/except with return in handler."""
        for child in ast.walk(node):
            if isinstance(child, ast.Try):
                for handler in child.handlers:
                    for stmt in handler.body:
                        if isinstance(stmt, ast.Return):
                            return True
        return False

    def _check_fail_soft_error_handling(self, node: ast.FunctionDef) -> None:
        """
        Rule 1: Fail-soft error handling

        Public module-level functions should not raise on bad input.
        Flag functions that have raise statements but no try/except handlers.
        """
        # Only check public module-level functions
        if self.class_depth > 0 or node.name.startswith('_'):
            return

        if self._is_rule_disabled(node.lineno, 'FAIL_SOFT_ERROR'):
            return

        has_raise = False
        for child in ast.walk(node):
            if isinstance(child, ast.Raise):
                has_raise = True
                break

        if has_raise:
            # Check if there are try/except blocks that handle errors gracefully
            if not self._has_try_except_with_return(node):
                self.violations.append(ConventionViolation(
                    self.filepath, node.lineno, 'FAIL_SOFT_ERROR',
                    f'Public function "{node.name}" raises on bad input; use try/except with sensible defaults instead'
                ))

    def _check_hardcoded_secrets(self, node: ast.Assign) -> None:
        """
        Rule 2: Hardcoded secrets in config keys

        Flag string literals that look like secrets (PASSWORD|TOKEN|SECRET|KEY=).
        """
        if self._is_rule_disabled(node.lineno, 'HARDCODED_SECRET'):
            return

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

    def _check_module_singletons(self, node: ast.FunctionDef) -> None:
        """
        Rule 3: Module-level singletons

        Functions should delegate to singleton instances, not define instance methods with 'self'.
        """
        if self._is_rule_disabled(node.lineno, 'MODULE_SINGLETON'):
            return

        # Only check public module-level functions
        if self.class_depth > 0 or node.name.startswith('_'):
            return

        # Check if function has 'self' parameter (should not be there)
        if node.args.args and node.args.args[0].arg == 'self':
            self.violations.append(ConventionViolation(
                self.filepath, node.lineno, 'MODULE_SINGLETON',
                f'Public module-level function "{node.name}" has "self" parameter; should delegate to singleton, not be instance method',
                severity='warn'
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

    if not path.exists():
        return violations

    for py_file in path.rglob('*.py'):
        # Skip common directories
        if any(part in py_file.parts for part in ['.git', '__pycache__', '.pytest_cache', 'node_modules']):
            continue
        violations.extend(check_file(str(py_file)))

    return violations


def main() -> int:
    """Main entry point."""
    parser = ArgumentParser(description='CLAUDE.md Convention Linter')
    parser.add_argument('paths', nargs='*',
                        help='Files or directories to check (default: stdin from pre-commit)')
    parser.add_argument('--check-path', dest='check_paths', action='append',
                        help='Additional paths to check (can be repeated)')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON')
    parser.add_argument('--fail-on', choices=['error', 'warn'], default='error',
                        help='Severity level that causes non-zero exit (default: error)')

    args = parser.parse_args()

    # Collect all paths to check
    check_paths = args.paths if args.paths else []
    if args.check_paths:
        check_paths.extend(args.check_paths)

    # If no paths provided, use defaults
    if not check_paths:
        check_paths = ['runner', 'tools']

    # Run linter on all paths
    all_violations = []
    for path in check_paths:
        path_obj = Path(path)
        if path_obj.is_dir():
            all_violations.extend(check_directory(path))
        elif path_obj.is_file():
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
