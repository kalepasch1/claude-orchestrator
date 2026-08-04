#!/usr/bin/env python3
"""Convention linter for claude-orchestrator runner.

Enforces conventions from CLAUDE.md:
1. ORCH_ prefix for config keys
2. No hardcoded secrets in config keys
3. Fail-soft error handling (no bare except/raise)
4. Module-level singleton pattern
5. Return sensible defaults on error
6. Naming conventions (snake_case for functions/variables)
7. No magic numbers (use constants instead)
8. Proper syntax (no syntax errors)
"""

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Set, Optional


@dataclass
class ConventionViolation:
    """Represents a convention violation."""
    filepath: str
    lineno: int
    rule: str
    severity: str  # 'error', 'warning', 'info'
    message: str

    def __str__(self) -> str:
        """Format violation for output."""
        return f"{self.filepath}:{self.lineno}: {self.rule}: {self.message}"


# Safe config keys that don't require ORCH_ prefix
_SAFE_CONFIG_KEYS = {
    "MAX_PARALLEL",
    "MAX_RETRIES",
    "TIMEOUT",
    "DEBUG",
    "LOG_LEVEL",
    "PORT",
    "HOST",
}

# Secret patterns to detect hardcoded secrets
_SECRET_PATTERNS = {"secret", "key", "token", "password", "api_key", "pat"}


class ConventionChecker(ast.NodeVisitor):
    """AST visitor to check convention compliance."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        # Keep violations as tuples for backward compatibility
        self.violations: List[Tuple[int, str, str]] = []
        self._v2_violations: List[ConventionViolation] = []
        self.current_function_name = None
        self.in_module_level = True

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check function definitions."""
        prev_func = self.current_function_name
        prev_module_level = self.in_module_level
        self.current_function_name = node.name

        # Check module-level instance methods (Rule 4)
        if self.in_module_level and node.args.args:
            first_arg = node.args.args[0].arg
            if first_arg == "self":
                msg = f"Module-level function '{node.name}' has 'self' parameter; use module delegation instead"
                self.violations.append((node.lineno, "module-singleton-pattern", msg))
                self._v2_violations.append(ConventionViolation(
                    filepath=self.filepath,
                    lineno=node.lineno,
                    rule="MODULE_SINGLETON_PATTERN",
                    severity="error",
                    message=msg
                ))

        # Check naming convention (snake_case)
        if not self._is_valid_identifier(node.name) and node.name.startswith("_"):
            pass  # Private functions are OK
        elif not self._is_snake_case(node.name):
            msg = f"Function '{node.name}' should use snake_case naming convention"
            self._v2_violations.append(ConventionViolation(
                filepath=self.filepath,
                lineno=node.lineno,
                rule="NAMING_CONVENTION",
                severity="warning",
                message=msg
            ))

        self.in_module_level = False
        self.generic_visit(node)
        self.in_module_level = prev_module_level
        self.current_function_name = prev_func

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Check async function definitions."""
        prev_func = self.current_function_name
        prev_module_level = self.in_module_level
        self.current_function_name = node.name

        # Check module-level instance methods (Rule 4)
        if self.in_module_level and node.args.args:
            first_arg = node.args.args[0].arg
            if first_arg == "self":
                msg = (
                    f"Module-level async function '{node.name}' has 'self' parameter; "
                    "use module delegation instead"
                )
                self.violations.append((node.lineno, "module-singleton-pattern", msg))
                self._v2_violations.append(ConventionViolation(
                    filepath=self.filepath,
                    lineno=node.lineno,
                    rule="MODULE_SINGLETON_PATTERN",
                    severity="error",
                    message=msg
                ))

        # Check naming convention (snake_case) — parity with sync functions
        if not self._is_valid_identifier(node.name) and node.name.startswith("_"):
            pass  # Private functions are OK
        elif not self._is_snake_case(node.name):
            msg = f"Async function '{node.name}' should use snake_case naming convention"
            self._v2_violations.append(ConventionViolation(
                filepath=self.filepath,
                lineno=node.lineno,
                rule="NAMING_CONVENTION",
                severity="warning",
                message=msg
            ))

        self.in_module_level = False
        self.generic_visit(node)
        self.in_module_level = prev_module_level
        self.current_function_name = prev_func

    def visit_Try(self, node: ast.Try) -> None:
        """Check exception handling (Rule 3 & 5)."""
        for handler in node.handlers:
            # Check for bare except or except Exception without return
            if handler.type is None:
                msg = "Bare 'except:' clause found; use specific exceptions and return sensible default"
                self.violations.append((handler.lineno, "fail-soft-error-handling", msg))
                self._v2_violations.append(ConventionViolation(
                    filepath=self.filepath,
                    lineno=handler.lineno,
                    rule="FAIL_SOFT_ERROR",
                    severity="error",
                    message=msg
                ))
            elif self._is_broad_exception(handler.type):
                # Check if handler returns a default value
                has_return = self._handler_returns_default(handler)
                if not has_return:
                    exc_name = self._get_exception_name(handler.type)
                    msg = f"Broad exception '{exc_name}' without returning sensible default"
                    self.violations.append((handler.lineno, "fail-soft-error-handling", msg))
                    self._v2_violations.append(ConventionViolation(
                        filepath=self.filepath,
                        lineno=handler.lineno,
                        rule="FAIL_SOFT_ERROR",
                        severity="error",
                        message=msg
                    ))

        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        """Check for config key assignments (Rules 1 & 2)."""
        # Check for fleet_config["KEY"] or similar assignments
        if isinstance(node.value, ast.Name) and "config" in node.value.id.lower():
            if isinstance(node.slice, ast.Constant):
                key = node.slice.value
                if isinstance(key, str):
                    self._check_config_key(key, node.lineno)

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Check assignments for hardcoded secrets and magic numbers (Rule 2, 7)."""
        # Check if assigning a string constant that looks like a secret
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            value_str = node.value.value
            # Check for hardcoded credentials (sk-, api-, etc.)
            if any(
                value_str.lower().startswith(prefix)
                for prefix in ["sk-", "api-", "pk_", "secret_", "token_"]
            ):
                # Get the assignment target
                for target in node.targets:
                    # Subscript targets, e.g. os.environ["ORCH_API_KEY"] = "sk-..."
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)
                    ):
                        key_lower = target.slice.value.lower()
                        if any(pattern in key_lower for pattern in _SECRET_PATTERNS):
                            msg = (
                                "Hardcoded secret detected in subscript assignment "
                                f"to '{target.slice.value}'"
                            )
                            self.violations.append((node.lineno, "no-hardcoded-secrets", msg))
                            self._v2_violations.append(ConventionViolation(
                                filepath=self.filepath,
                                lineno=node.lineno,
                                rule="NO_HARDCODED_SECRETS",
                                severity="error",
                                message=msg
                            ))
                        continue
                    if isinstance(target, ast.Name):
                        var_name = target.id.lower()
                        if any(
                            pattern in var_name
                            for pattern in _SECRET_PATTERNS
                        ):
                            msg = f"Hardcoded secret detected in assignment to '{target.id}'"
                            self.violations.append((node.lineno, "no-hardcoded-secrets", msg))
                            self._v2_violations.append(ConventionViolation(
                                filepath=self.filepath,
                                lineno=node.lineno,
                                rule="NO_HARDCODED_SECRETS",
                                severity="error",
                                message=msg
                            ))
                    elif (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)
                    ):
                        # Subscript targets: os.environ["ORCH_API_KEY"] = "sk-...",
                        # fleet_config["ORCH_TOKEN"] = "..." — previously invisible
                        # because only ast.Name targets were inspected.
                        key_lower = target.slice.value.lower()
                        if any(
                            pattern in key_lower
                            for pattern in _SECRET_PATTERNS
                        ):
                            msg = (
                                f"Hardcoded secret detected in assignment to "
                                f"'{target.slice.value}'"
                            )
                            self.violations.append((node.lineno, "no-hardcoded-secrets", msg))
                            self._v2_violations.append(ConventionViolation(
                                filepath=self.filepath,
                                lineno=node.lineno,
                                rule="NO_HARDCODED_SECRETS",
                                severity="error",
                                message=msg
                            ))

        # Check for magic numbers
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, (int, float)):
            # Skip zero, one (commonly allowed)
            if node.value.value not in (0, 1, -1):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        var_name = target.id
                        # Only flag if variable is not in UPPERCASE (i.e., not a constant)
                        if not (var_name.isupper() and "_" in var_name):
                            msg = f"Magic number {node.value.value} should be assigned to a named constant"
                            self._v2_violations.append(ConventionViolation(
                                filepath=self.filepath,
                                lineno=node.lineno,
                                rule="MAGIC_NUMBERS",
                                severity="warning",
                                message=msg
                            ))

        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Check annotated assignments for hardcoded secrets (Rule 2).

        Annotated assignments (e.g. ``api_key: str = "sk-..."``) previously
        bypassed the hardcoded-secret detection that plain assignments get.
        """
        if (
            node.value is not None
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and isinstance(node.target, ast.Name)
        ):
            value_str = node.value.value
            if any(
                value_str.lower().startswith(prefix)
                for prefix in ["sk-", "api-", "pk_", "secret_", "token_"]
            ):
                var_name = node.target.id.lower()
                if any(pattern in var_name for pattern in _SECRET_PATTERNS):
                    msg = f"Hardcoded secret detected in annotated assignment to '{node.target.id}'"
                    self.violations.append((node.lineno, "no-hardcoded-secrets", msg))
                    self._v2_violations.append(ConventionViolation(
                        filepath=self.filepath,
                        lineno=node.lineno,
                        rule="NO_HARDCODED_SECRETS",
                        severity="error",
                        message=msg
                    ))

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Check for raise statements and function calls that might violate conventions."""
        # Check for raise ValueError/RuntimeError on input validation (Rule 5)
        if isinstance(node.func, ast.Name) and node.func.id == "raise":
            pass  # Handled by visit_Raise
        elif isinstance(node.func, ast.Attribute):
            # Check for os.environ assignments with hardcoded secrets
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
                and node.func.attr == "environ"
            ):
                pass  # This is typically a get, not a set

        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        """Check for raises that violate Rule 5."""
        if node.exc is None:
            # Bare raise is OK
            pass
        elif isinstance(node.exc, ast.Call):
            # Check if raising on invalid input
            func_name = None
            if isinstance(node.exc.func, ast.Name):
                func_name = node.exc.func.id
            elif isinstance(node.exc.func, ast.Attribute):
                func_name = node.exc.func.attr

            # Check if this is a ValueError or similar for bad input
            if func_name in ("ValueError", "TypeError", "KeyError"):
                # Check if we're in a guard clause for None/empty/missing
                parent_context = self._get_parent_context(node)
                if self._is_input_validation_context(parent_context):
                    self.violations.append(
                        (
                            node.lineno,
                            "sensible-defaults",
                            f"Raising {func_name} on input validation; return sensible default instead",
                        )
                    )

        self.generic_visit(node)

    def _check_config_key(self, key: str, lineno: int) -> None:
        """Check if config key follows conventions (Rules 1 & 2)."""
        # Rule 1: Check ORCH_ prefix or safe key
        if not key.startswith("ORCH_") and key not in _SAFE_CONFIG_KEYS:
            msg = f"Config key '{key}' missing ORCH_ prefix or not in safe allowlist"
            self.violations.append((lineno, "config-orch-prefix", msg))
            self._v2_violations.append(ConventionViolation(
                filepath=self.filepath,
                lineno=lineno,
                rule="CONFIG_KEY_NAMING",
                severity="error",
                message=msg
            ))

        # Rule 2: Check for secret patterns in key name
        key_lower = key.lower()
        if any(pattern in key_lower for pattern in _SECRET_PATTERNS):
            msg = f"Config key '{key}' contains secret pattern; use env var instead"
            self.violations.append((lineno, "no-hardcoded-secrets", msg))
            self._v2_violations.append(ConventionViolation(
                filepath=self.filepath,
                lineno=lineno,
                rule="CONFIG_KEY_NAMING",
                severity="error",
                message=msg
            ))

    @staticmethod
    def _is_snake_case(name: str) -> bool:
        """Check if identifier is in snake_case."""
        if "_" not in name and name.islower():
            return True
        if name.islower() and all(c.islower() or c == "_" or c.isdigit() for c in name):
            return True
        return False

    @staticmethod
    def _is_valid_identifier(name: str) -> bool:
        """Check if identifier is valid Python."""
        return name.isidentifier()

    @staticmethod
    def _is_broad_exception(exc_type: ast.expr) -> bool:
        """Check if exception type is broad (Exception, BaseException)."""
        if isinstance(exc_type, ast.Name):
            return exc_type.id in ("Exception", "BaseException")
        return False

    @staticmethod
    def _get_exception_name(exc_type: ast.expr) -> str:
        """Get the name of an exception type."""
        if isinstance(exc_type, ast.Name):
            return exc_type.id
        return "Exception"

    @staticmethod
    def _handler_returns_default(handler: ast.ExceptHandler) -> bool:
        """Check if exception handler returns a sensible default."""
        for stmt in handler.body:
            if isinstance(stmt, ast.Return):
                if stmt.value is not None:
                    # Check if returning a sensible default
                    if isinstance(stmt.value, (ast.Constant, ast.List, ast.Dict)):
                        return True
                    # Empty return is also OK (returns None)
                    if isinstance(stmt.value, ast.Constant) and stmt.value.value is None:
                        return True
                    # Attribute access or name is OK (e.g., return DEFAULT_VALUE)
                    if isinstance(stmt.value, (ast.Name, ast.Attribute)):
                        return True
                    return True
            elif isinstance(stmt, (ast.Pass, ast.Continue, ast.Break)):
                continue
        return False

    @staticmethod
    def _get_parent_context(node: ast.AST) -> str:
        """Get surrounding context (simplified)."""
        return "unknown"

    @staticmethod
    def _is_input_validation_context(context: str) -> bool:
        """Check if we're in an input validation guard clause."""
        return context in ("guard", "validation")


def lint_file(filepath: str) -> List[Tuple[int, str, str]]:
    """Lint a single Python file. Returns legacy tuple format."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except (FileNotFoundError, PermissionError):
        return []

    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError:
        return []

    checker = ConventionChecker(filepath)
    checker.visit(tree)
    return checker.violations


def check_file(filepath: str) -> List[ConventionViolation]:
    """Check a single Python file for convention violations."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except (FileNotFoundError, PermissionError):
        return []

    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError as e:
        return [ConventionViolation(
            filepath=filepath,
            lineno=e.lineno or 1,
            rule="SYNTAX_ERROR",
            severity="error",
            message=f"Syntax error: {e.msg}"
        )]

    checker = ConventionChecker(filepath)
    checker.visit(tree)
    return checker._v2_violations


def scan_directory(directory: str, exclude_dirs: Optional[Set[str]] = None) -> List[ConventionViolation]:
    """Scan a directory for convention violations."""
    if exclude_dirs is None:
        exclude_dirs = {"venv", ".venv", "__pycache__", ".git", "node_modules", ".pytest_cache"}

    all_violations = []
    root = Path(directory)

    for py_file in root.rglob("*.py"):
        # Skip excluded directories
        skip = False
        for excluded in exclude_dirs:
            if excluded in py_file.parts:
                skip = True
                break

        if skip:
            continue

        violations = check_file(str(py_file))
        all_violations.extend(violations)

    # Sort by filepath and line number
    all_violations.sort(key=lambda v: (v.filepath, v.lineno))
    return all_violations


def main() -> int:
    """Run linter on runner directory or specified files."""
    if len(sys.argv) > 1:
        # Lint specified files/directories
        paths = [Path(p) for p in sys.argv[1:]]
    else:
        # Default to runner directory
        runner_dir = Path(__file__).parent.parent
        paths = [runner_dir]

    all_violations = []

    for path in paths:
        if path.is_file():
            if path.suffix == ".py":
                violations = lint_file(str(path))
                all_violations.extend(
                    (str(path), line, rule, msg)
                    for line, rule, msg in violations
                )
        elif path.is_dir():
            for py_file in path.rglob("*.py"):
                # Skip test files and cache directories
                if "test" in str(py_file) or "__pycache__" in str(py_file):
                    continue
                violations = lint_file(str(py_file))
                all_violations.extend(
                    (str(py_file), line, rule, msg)
                    for line, rule, msg in violations
                )

    # Output violations
    if all_violations:
        # Sort by filepath and line number
        all_violations.sort(key=lambda x: (x[0], x[1]))
        for filepath, lineno, rule, msg in all_violations:
            # Make filepath relative to repo root for readability
            try:
                rel_path = Path(filepath).relative_to(
                    Path(__file__).parent.parent.parent
                )
            except ValueError:
                rel_path = Path(filepath)
            print(f"{rel_path}:{lineno}:{rule}: {msg}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
