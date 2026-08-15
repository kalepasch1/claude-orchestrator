#!/usr/bin/env python3
"""
Convention Linter for CLAUDE.md Conventions - Production Implementation

Enforces 3 core conventions:
1. Fail-soft error handling: Return sensible defaults, don't raise on bad input
2. No hardcoded secrets: Use os.environ for sensitive config
3. Module-level singletons: Delegate from public functions to instances

Severity levels:
- FAIL: Blocks merge (violates core invariants)
- WARN: Non-blocking advisory (style/best-practice)
- REPORT: Info-only (observations, no action required)

Usage:
    python tools/convention_linter.py [paths...] [--json] [--fail-on=fail]

Output:
    Text: file:line: RULE: message [SEVERITY]
    JSON: {"file": str, "line": int, "rule": str, "message": str, "severity": str}

Exit codes:
    0 = No violations (or violations below --fail-on threshold)
    1 = Violations found at or above --fail-on threshold
"""
import ast
import json
import os
import re
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple


class ConventionViolation:
    """Represents a single convention violation."""

    SEVERITIES = {"fail": 0, "warn": 1, "report": 2}

    def __init__(
        self,
        filepath: str,
        lineno: int,
        rule: str,
        message: str,
        severity: str = "fail",
    ):
        self.filepath = filepath
        self.lineno = lineno
        self.rule = rule
        self.message = message
        self.severity = severity.lower()

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
        return f"{self.filepath}:{self.lineno}: {self.rule}: {self.message} [{self.severity.upper()}]"

    def __repr__(self) -> str:
        return str(self)

    def __lt__(self, other: "ConventionViolation") -> bool:
        """Sort by severity (fail < warn < report), then file, then line."""
        if self.severity != other.severity:
            return self.SEVERITIES.get(self.severity, 99) < self.SEVERITIES.get(
                other.severity, 99
            )
        if self.filepath != other.filepath:
            return self.filepath < other.filepath
        return self.lineno < other.lineno


class ConventionChecker(ast.NodeVisitor):
    """AST visitor that checks Python code for convention violations."""

    def __init__(self, filepath: str, source_lines: List[str]):
        self.filepath = filepath
        self.source_lines = source_lines
        self.violations: List[ConventionViolation] = []
        self.function_context: List[Tuple[str, int]] = []
        self.class_depth = 0
        self.noqa_lines = self._parse_noqa_directives()

    def _parse_noqa_directives(self) -> Dict[int, set]:
        """Parse # noqa: RULE_NAME comments to skip specific lines."""
        noqa = {}
        for i, line in enumerate(self.source_lines, 1):
            if "# noqa" in line:
                match = re.search(r"#\s*noqa(?::\s*(\w+(?:,\s*\w+)*))?", line)
                if match:
                    if match.group(1):
                        rules = {r.strip() for r in match.group(1).split(",")}
                    else:
                        rules = {"*"}  # noqa without rule name disables all
                    noqa[i] = rules
        return noqa

    def _should_skip(self, lineno: int, rule: str) -> bool:
        """Check if a rule is disabled for this line via # noqa."""
        noqa = self.noqa_lines.get(lineno, set())
        return "*" in noqa or rule in noqa

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track class context to distinguish methods from module functions."""
        self.class_depth += 1
        self.generic_visit(node)
        self.class_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check function definitions."""
        if not node.name.startswith("_"):
            self.function_context.append((node.name, self.class_depth))
            self._check_fail_soft_error_handling(node)
            self._check_module_singleton_pattern(node)
        self.generic_visit(node)
        if not node.name.startswith("_"):
            self.function_context.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Check async function definitions."""
        if not node.name.startswith("_"):
            self.function_context.append((node.name, self.class_depth))
            self._check_fail_soft_error_handling(node)
            self._check_module_singleton_pattern(node)
        self.generic_visit(node)
        if not node.name.startswith("_"):
            self.function_context.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        """Check assignments for hardcoded secrets."""
        self._check_hardcoded_secrets(node)
        self.generic_visit(node)

    def _check_fail_soft_error_handling(self, node: ast.FunctionDef) -> None:
        """
        Rule 1: Fail-soft error handling

        Public module-level functions must return sensible defaults on errors,
        not raise on bad input. Exception handlers must have return statements.
        """
        if self._should_skip(node.lineno, "FAIL_SOFT_ERROR"):
            return

        # Only check public module-level functions
        if self.class_depth > 0:
            return

        # Find all try/except blocks
        try_blocks = []
        for child in ast.walk(node):
            if isinstance(child, ast.Try):
                try_blocks.append(child)

        # Check each exception handler has a return statement
        for try_block in try_blocks:
            for handler in try_block.handlers:
                has_return = any(isinstance(stmt, ast.Return) for stmt in handler.body)
                has_raise = any(isinstance(stmt, ast.Raise) for stmt in handler.body)

                if not has_return and not has_raise:
                    # Check if body is empty or only has pass/print
                    meaningful = [
                        stmt
                        for stmt in handler.body
                        if not isinstance(stmt, (ast.Pass, ast.Expr))
                    ]
                    if not meaningful or all(
                        isinstance(stmt, ast.Expr)
                        and isinstance(stmt.value, ast.Call)
                        for stmt in meaningful
                    ):
                        self.violations.append(
                            ConventionViolation(
                                self.filepath,
                                handler.lineno,
                                "FAIL_SOFT_ERROR",
                                f'Exception handler for "{node.name}" must return sensible default (empty string, None, {{}}, etc.)',
                                "fail",
                            )
                        )

    def _check_hardcoded_secrets(self, node: ast.Assign) -> None:
        """
        Rule 2: Hardcoded secrets in config keys

        Flag string literals assigned to variables/keys with secret keywords.
        """
        if self._should_skip(node.lineno, "HARDCODED_SECRET"):
            return

        secret_patterns = [
            r"PASSWORD",
            r"TOKEN",
            r"SECRET",
            r"API_KEY",
            r"PRIVATE_KEY",
            r"AUTH",
            r"CREDENTIAL",
        ]
        secret_regex = re.compile("|".join(secret_patterns), re.IGNORECASE)

        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            value = node.value.value

            # Skip environment variable placeholders like $SECRET or ${SECRET}
            if value.startswith("$"):
                return

            for target in node.targets:
                if isinstance(target, ast.Name):
                    var_name = target.id
                    if secret_regex.search(var_name):
                        self.violations.append(
                            ConventionViolation(
                                self.filepath,
                                node.lineno,
                                "HARDCODED_SECRET",
                                f'Variable "{var_name}" contains secret keyword; use os.environ instead',
                                "fail",
                            )
                        )
                elif isinstance(target, ast.Subscript):
                    if isinstance(target.slice, ast.Constant) and isinstance(
                        target.slice.value, str
                    ):
                        key_name = target.slice.value
                        if secret_regex.search(key_name):
                            self.violations.append(
                                ConventionViolation(
                                    self.filepath,
                                    node.lineno,
                                    "HARDCODED_SECRET",
                                    f'Config key "{key_name}" contains secret keyword; use os.environ instead',
                                    "fail",
                                )
                            )

    def _check_module_singleton_pattern(self, node: ast.FunctionDef) -> None:
        """
        Rule 3: Module-level singletons

        Module-level (public) functions should not have 'self' as first parameter.
        Advisory/warning level.
        """
        if self._should_skip(node.lineno, "MODULE_SINGLETON"):
            return

        # Only check public module-level functions
        if self.class_depth > 0:
            return

        if node.args.args and len(node.args.args) > 0:
            first_arg = node.args.args[0]
            if first_arg.arg == "self":
                self.violations.append(
                    ConventionViolation(
                        self.filepath,
                        node.lineno,
                        "MODULE_SINGLETON",
                        f'Public function "{node.name}" should not have "self" parameter; use singleton pattern instead',
                        "warn",
                    )
                )


def check_file(filepath: str) -> List[ConventionViolation]:
    """Parse and check a Python file for convention violations."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        source_lines = source.split("\n")

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return [
                ConventionViolation(
                    filepath,
                    e.lineno or 1,
                    "SYNTAX_ERROR",
                    f"Syntax error: {e.msg}",
                    "report",
                )
            ]

        checker = ConventionChecker(filepath, source_lines)
        checker.visit(tree)
        return checker.violations
    except Exception as e:
        return [
            ConventionViolation(
                filepath,
                1,
                "CHECK_ERROR",
                f"Error checking file: {str(e)}",
                "report",
            )
        ]


def check_directory(
    directory: str, exclude_dirs: Optional[List[str]] = None
) -> List[ConventionViolation]:
    """Check all Python files in a directory."""
    if exclude_dirs is None:
        exclude_dirs = [".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv"]

    violations = []
    path = Path(directory).resolve()

    if not path.exists():
        return []

    for py_file in path.rglob("*.py"):
        # Skip excluded directories
        if any(part in py_file.parts for part in exclude_dirs):
            continue
        violations.extend(check_file(str(py_file)))

    return violations


def main() -> int:
    """Main entry point."""
    parser = ArgumentParser(
        description="Convention Linter for CLAUDE.md Conventions",
        epilog="Exit code: 0 = ok, 1 = violations at/above --fail-on threshold",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["runner", "tools"],
        help="Files or directories to check (default: runner, tools)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--fail-on",
        choices=["fail", "warn", "report"],
        default="fail",
        help="Severity level that causes non-zero exit (default: fail)",
    )

    args = parser.parse_args()

    # Collect all paths to check
    check_paths = args.paths or ["runner", "tools"]

    # Run linter on all paths
    all_violations = []
    for path_str in check_paths:
        path = Path(path_str)
        if path.is_dir():
            all_violations.extend(check_directory(str(path)))
        elif path.is_file():
            all_violations.extend(check_file(str(path)))

    # Sort violations
    all_violations.sort()

    # Output results
    if args.json:
        output = [v.to_dict() for v in all_violations]
        print(json.dumps(output, indent=2))
    else:
        for violation in all_violations:
            print(str(violation))

    # Determine exit code based on severity threshold
    severity_threshold = ConventionViolation.SEVERITIES[args.fail_on]
    failing_violations = [
        v
        for v in all_violations
        if ConventionViolation.SEVERITIES.get(v.severity, 99) <= severity_threshold
    ]

    return 1 if failing_violations else 0


if __name__ == "__main__":
    sys.exit(main())
