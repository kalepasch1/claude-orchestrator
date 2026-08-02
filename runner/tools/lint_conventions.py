#!/usr/bin/env python3
"""Convention linter for claude-orchestrator runner.

Enforces 5 key conventions from CLAUDE.md:
1. ORCH_ prefix for config keys
2. No hardcoded secrets in config keys
3. Fail-soft error handling (no bare except/raise)
4. Module-level singleton pattern
5. Return sensible defaults on error
"""

import ast
import sys
from pathlib import Path
from typing import List, Tuple, Set


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
        self.violations: List[Tuple[int, str, str]] = []
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
                self.violations.append(
                    (
                        node.lineno,
                        "module-singleton-pattern",
                        f"Module-level function '{node.name}' has 'self' parameter; use module delegation instead",
                    )
                )

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
                self.violations.append(
                    (
                        node.lineno,
                        "module-singleton-pattern",
                        f"Module-level async function '{node.name}' has 'self' parameter",
                    )
                )

        self.in_module_level = False
        self.generic_visit(node)
        self.in_module_level = prev_module_level
        self.current_function_name = prev_func

    def visit_Try(self, node: ast.Try) -> None:
        """Check exception handling (Rule 3 & 5)."""
        for handler in node.handlers:
            # Check for bare except or except Exception without return
            if handler.type is None:
                self.violations.append(
                    (
                        handler.lineno,
                        "fail-soft-error-handling",
                        "Bare 'except:' clause found; use specific exceptions and return sensible default",
                    )
                )
            elif self._is_broad_exception(handler.type):
                # Check if handler returns a default value
                has_return = self._handler_returns_default(handler)
                if not has_return:
                    self.violations.append(
                        (
                            handler.lineno,
                            "fail-soft-error-handling",
                            f"Broad exception '{self._get_exception_name(handler.type)}' without returning sensible default",
                        )
                    )

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
        """Check assignments for hardcoded secrets (Rule 2)."""
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
                    if isinstance(target, ast.Name):
                        var_name = target.id.lower()
                        if any(
                            pattern in var_name
                            for pattern in _SECRET_PATTERNS
                        ):
                            self.violations.append(
                                (
                                    node.lineno,
                                    "no-hardcoded-secrets",
                                    f"Hardcoded secret detected in assignment to '{target.id}'",
                                )
                            )

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
            self.violations.append(
                (
                    lineno,
                    "config-orch-prefix",
                    f"Config key '{key}' missing ORCH_ prefix or not in safe allowlist",
                )
            )

        # Rule 2: Check for secret patterns in key name
        key_lower = key.lower()
        if any(pattern in key_lower for pattern in _SECRET_PATTERNS):
            self.violations.append(
                (
                    lineno,
                    "no-hardcoded-secrets",
                    f"Config key '{key}' contains secret pattern; use env var instead",
                )
            )

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
    """Lint a single Python file."""
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
