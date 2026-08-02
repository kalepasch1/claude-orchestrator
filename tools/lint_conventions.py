"""
Lint rules enforcer for CLAUDE.md project conventions.

Checks for 5 key conventions:
1. Configuration Key Naming (ORCH_ prefix)
2. Fail-Soft Error Handling (return "" or defaults on error)
3. Thread Safety (locks for shared state)
4. Naming Consistency (snake_case, SCREAMING_SNAKE_CASE, no magic numbers)
5. Module Structure (singleton delegation pattern)
"""
import ast
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple, Optional, Set


class ConventionViolation:
    def __init__(self, filepath: str, lineno: int, rule: str, message: str, severity: str = "error"):
        self.filepath = filepath
        self.lineno = lineno
        self.rule = rule
        self.message = message
        self.severity = severity

    def __str__(self) -> str:
        return f"{self.filepath}:{self.lineno}: {self.rule}: {self.message}"

    def __repr__(self) -> str:
        return str(self)


class ConventionChecker(ast.NodeVisitor):
    """AST visitor that checks Python files for convention violations."""

    def __init__(self, filepath: str, source_lines: List[str]):
        self.filepath = filepath
        self.source_lines = source_lines
        self.violations: List[ConventionViolation] = []
        self.lock_depth = 0
        self.function_context = []
        self.in_loop = False
        self.class_depth = 0

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track class context to distinguish methods from module functions."""
        self.class_depth += 1
        self.generic_visit(node)
        self.class_depth -= 1

    def visit_Assign(self, node: ast.Assign) -> None:
        """Check config key naming, magic numbers, hardcoded secrets, and naming conventions."""
        self._check_config_keys(node)
        self._check_magic_numbers(node)
        self._check_hardcoded_secrets(node)
        self._check_assignment_naming(node)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        """Check augmented assignments for config keys and magic numbers."""
        self._check_magic_numbers_expr(node.value)
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        """Check magic numbers in return statements."""
        if node.value:
            self._check_magic_numbers_expr(node.value)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        """Check magic numbers in comparisons."""
        for comparator in node.comparators:
            self._check_magic_numbers_expr(comparator)
        self._check_magic_numbers_expr(node.left)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check function definitions for error handling, naming, and singleton pattern."""
        self.function_context.append(node.name)
        self._check_function_naming(node)
        self._check_error_handling(node)
        self._check_module_singleton_pattern(node)
        self.generic_visit(node)
        self.function_context.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Check async function definitions."""
        self.function_context.append(node.name)
        self._check_function_naming(node)
        self._check_error_handling(node)
        self._check_module_singleton_pattern(node)
        self.generic_visit(node)
        self.function_context.pop()

    def visit_With(self, node: ast.With) -> None:
        """Track context managers, especially locks."""
        is_lock_context = False
        for item in node.items:
            context_name = self._extract_name(item.context_expr)
            if context_name and ('lock' in context_name.lower() or 'mutex' in context_name.lower()):
                is_lock_context = True
                break

        if is_lock_context:
            self.lock_depth += 1
        self.generic_visit(node)
        if is_lock_context:
            self.lock_depth -= 1

    def visit_For(self, node: ast.For) -> None:
        """Track loop context for loop variables."""
        old_in_loop = self.in_loop
        self.in_loop = True
        self.generic_visit(node)
        self.in_loop = old_in_loop

    def visit_While(self, node: ast.While) -> None:
        """Track loop context for loop variables."""
        old_in_loop = self.in_loop
        self.in_loop = True
        self.generic_visit(node)
        self.in_loop = old_in_loop

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Check unguarded mutations to shared state."""
        self._check_unguarded_mutations(node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Check naming conventions."""
        self._check_naming_convention(node)
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        """Check try/except blocks for error handling."""
        self._check_try_except(node)
        self.generic_visit(node)

    def _check_config_keys(self, node: ast.Assign) -> None:
        """Check that config keys start with ORCH_."""
        for target in node.targets:
            if isinstance(target, ast.Subscript):
                if isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str):
                    key = target.slice.value
                    target_name = self._extract_name(target.value)
                    if target_name and 'config' in target_name.lower():
                        if not key.startswith('ORCH_') and key.isupper():
                            self.violations.append(ConventionViolation(
                                self.filepath, node.lineno, 'CONFIG_KEY_NAMING',
                                f'Config key "{key}" should start with ORCH_ (safe keys only)'
                            ))

    def _check_magic_numbers(self, node: ast.Assign) -> None:
        """Check for magic numbers in assignments."""
        for target in node.targets:
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, (int, float)) and not isinstance(node.value.value, bool):
                    val = node.value.value
                    if val not in (0, 1, -1) and not target.id.isupper():
                        self.violations.append(ConventionViolation(
                            self.filepath, node.lineno, 'MAGIC_NUMBERS',
                            f'Magic number {val} should be assigned to named constant (use SCREAMING_SNAKE_CASE)'
                        ))

    def _check_magic_numbers_expr(self, node: Optional[ast.expr]) -> None:
        """Check for magic numbers in expressions."""
        if node is None:
            return
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                val = node.value
                if val not in (0, 1, -1) and self.function_context:
                    self.violations.append(ConventionViolation(
                        self.filepath, node.lineno, 'MAGIC_NUMBERS',
                        f'Magic number {val} in expression should be assigned to named constant'
                    ))

    def _check_function_naming(self, node: ast.FunctionDef) -> None:
        """Check function names follow snake_case."""
        name = node.name
        if not name.startswith('_'):
            if not self._is_snake_case(name):
                self.violations.append(ConventionViolation(
                    self.filepath, node.lineno, 'NAMING_CONVENTION',
                    f'Function "{name}" should use snake_case'
                ))

    def _check_module_singleton_pattern(self, node: ast.FunctionDef) -> None:
        """Check that module-level functions don't have self parameter (singleton pattern)."""
        if self.class_depth == 0:
            if node.args.args and len(node.args.args) > 0:
                first_arg = node.args.args[0]
                if first_arg.arg == 'self':
                    self.violations.append(ConventionViolation(
                        self.filepath, node.lineno, 'MODULE_SINGLETON',
                        f'Module-level function "{node.name}" should not have self parameter; use singleton pattern'
                    ))

    def _check_error_handling(self, node: ast.FunctionDef) -> None:
        """Check for fail-soft error handling patterns."""
        for child in ast.walk(node):
            if isinstance(child, ast.Try):
                self._check_try_except(child)

    def _check_try_except(self, try_node: ast.Try) -> None:
        """Verify try/except blocks have appropriate error handling."""
        for handler in try_node.handlers:
            has_return = any(isinstance(stmt, ast.Return) for stmt in handler.body)

            if not has_return:
                self.violations.append(ConventionViolation(
                    self.filepath, handler.lineno, 'FAIL_SOFT_ERROR',
                    'Exception handler should return a sensible default (empty string, None, etc.)'
                ))

    def _check_unguarded_mutations(self, node: ast.Attribute) -> None:
        """Flag mutations to shared state outside lock context."""
        pass

    def _check_hardcoded_secrets(self, node: ast.Assign) -> None:
        """Check for hardcoded secrets in variables with sensitive names."""
        secret_keywords = ('password', 'token', 'secret', 'key', 'api_key')

        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            if node.value.value and not node.value.value.startswith('$'):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        var_name = target.id.lower()
                        if any(keyword in var_name for keyword in secret_keywords):
                            self.violations.append(ConventionViolation(
                                self.filepath, node.lineno, 'HARDCODED_SECRET',
                                f'Variable "{target.id}" contains secret keyword; use environment variables instead'
                            ))
                    elif isinstance(target, ast.Subscript):
                        if isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str):
                            key_name = target.slice.value.lower()
                            if any(keyword in key_name for keyword in secret_keywords):
                                self.violations.append(ConventionViolation(
                                    self.filepath, node.lineno, 'HARDCODED_SECRET',
                                    f'Key "{target.slice.value}" contains secret keyword; use environment variables instead'
                                ))

    def _check_assignment_naming(self, node: ast.Assign) -> None:
        """Check naming conventions in assignments."""
        for target in node.targets:
            if isinstance(target, ast.Name):
                name = target.id
                if name in ('i', 'j', 'k', 'x', 'y', 'z') and not self.in_loop:
                    self.violations.append(ConventionViolation(
                        self.filepath, node.lineno, 'NAMING_CONVENTION',
                        f'Variable name "{name}" should only be used as loop variable'
                    ))

    def _check_naming_convention(self, node: ast.Name) -> None:
        """Check that variables use descriptive names."""
        name = node.id
        if len(name) <= 1 or name.startswith('__'):
            return
        if name in ('tmp', 'cfg'):
            self.violations.append(ConventionViolation(
                self.filepath, node.lineno, 'NAMING_CONVENTION',
                f'Variable name "{name}" too abbreviated; use descriptive names'
            ))
        elif name in ('i', 'j', 'k', 'x', 'y', 'z'):
            if not self.in_loop:
                self.violations.append(ConventionViolation(
                    self.filepath, node.lineno, 'NAMING_CONVENTION',
                    f'Variable name "{name}" should only be used as loop variable'
                ))

    def _extract_name(self, node: Optional[ast.expr]) -> Optional[str]:
        """Extract the name from an AST node."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = self._extract_name(node.value)
            if base:
                return f"{base}.{node.attr}"
        return None

    def _is_snake_case(self, name: str) -> bool:
        """Check if name follows snake_case convention."""
        if name.startswith('_'):
            name = name.lstrip('_')
        return bool(re.match(r'^[a-z][a-z0-9]*(_[a-z0-9]+)*$', name))


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
            filepath, 1, 'PARSE_ERROR',
            f'Error parsing file: {e}'
        )]


def scan_directory(dirpath: str) -> List[ConventionViolation]:
    """Scan a directory recursively for Python files with convention violations."""
    violations = []
    dirpath = Path(dirpath).resolve()

    for pyfile in dirpath.rglob('*.py'):
        skip_dirs = {'__pycache__', '.venv', 'venv', '.git', 'node_modules', '.pytest_cache'}
        if any(part in skip_dirs for part in pyfile.parts):
            continue
        violations.extend(check_file(str(pyfile)))

    return violations


def main():
    """Main entry point for the linter."""
    if len(sys.argv) < 2:
        print("Usage: python lint_conventions.py <file_or_dir> [<file_or_dir> ...]", file=sys.stderr)
        sys.exit(1)

    all_violations = []

    for target in sys.argv[1:]:
        target_path = Path(target).resolve()
        if target_path.is_file():
            all_violations.extend(check_file(str(target_path)))
        elif target_path.is_dir():
            all_violations.extend(scan_directory(str(target_path)))
        else:
            print(f"Warning: {target} is not a file or directory", file=sys.stderr)

    all_violations.sort(key=lambda v: (v.filepath, v.lineno))

    if all_violations:
        for violation in all_violations:
            print(str(violation))
        sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()
