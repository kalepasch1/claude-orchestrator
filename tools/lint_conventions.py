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
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple, Optional, Set


#: A regex EXTENSION GROUP -- `(?:`, `(?=`, `(?!`, `(?<`, `(?P<`. Deliberately NOT the
#: looser markers (\b, \d, [A-Z], .*), which do occur inside real key material; keying
#: on those would blind the rule to genuine leaks. An extension group is grammar, not
#: content: credentials do not contain "(?" followed by one of ":=!<P".
_REGEX_EXTENSION_GROUP_RE = re.compile(r'\(\?[:=!<P]')


def _is_regex_source(value: str) -> bool:
    """True when a literal is the source of a PATTERN rather than a value.

    Mirrors _is_regex_source in tools/convention_lint.py. Both linters carry it
    because both fired on the redaction pattern in runner/patch_templates.py --
    the regex that keeps prompt credentials out of the shared patch-template
    store -- and on their own detectors.
    """
    return bool(_REGEX_EXTENSION_GROUP_RE.search(str(value or '')))


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
        """Check function definitions for naming and the singleton pattern.

        Error handling is NOT checked here: visit_Try already fires for every try/except
        in the module. See _check_error_handling for what the extra walk was costing.
        """
        self.function_context.append(node.name)
        self._check_function_naming(node)
        self._check_module_singleton_pattern(node)
        self.generic_visit(node)
        self.function_context.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Check async function definitions (see visit_FunctionDef)."""
        self.function_context.append(node.name)
        self._check_function_naming(node)
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

    #: Method names the standard library DEFINES, in the case it defines them in.
    #:
    #: unittest calls setUp/tearDown/setUpClass/tearDownClass by exact name; a rule
    #: telling you to rename them to snake_case is telling you to break the
    #: framework, and the only way to comply is to stop using unittest. Flagging
    #: them taught readers that NAMING_CONVENTION hits are things you cannot act
    #: on, which is how a linter stops being read. Ten test files in runner/tests
    #: alone carry these; they were all sitting in the grandfathered baseline.
    _FRAMEWORK_METHOD_NAMES = frozenset({
        "setUp", "tearDown", "setUpClass", "tearDownClass",
        "setUpModule", "tearDownModule", "addTypeEqualityFunc",
        "assertEqual", "assertTrue", "assertFalse", "assertRaises",
        "runTest", "shortDescription", "subTest", "maxDiff",
    })

    def _check_function_naming(self, node: ast.FunctionDef) -> None:
        """Check function names follow snake_case."""
        name = node.name
        if name in self._FRAMEWORK_METHOD_NAMES:
            return
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
        """Report fail-soft violations for one function subtree, without the visitor.

        NOT called during a normal visit, and deliberately so. It used to run from
        visit_FunctionDef, walking the whole function body for Try nodes — while
        visit_Try was already reporting every one of them. Every handler inside a
        function was therefore filed TWICE, and a handler inside a nested function
        three times (outer walk + inner walk + visit_Try), so both the printed output
        and the ratchet baseline carried a ~2x phantom multiplier on FAIL_SOFT_ERROR,
        and adding one try/except moved the count by an unpredictable 1-3.

        Kept as a standalone entry point for callers that want the check on a single
        function subtree; visit_Try is the one that runs during a file scan.
        """
        for child in ast.walk(node):
            if isinstance(child, ast.Try):
                self._check_try_except(child)

    def _check_try_except(self, try_node: ast.Try) -> None:
        """Verify try/except blocks have appropriate error handling.

        The rule is named FAIL_SOFT_ERROR and the defect it exists to catch is a
        handler that swallows an exception and says nothing — the shape that made
        four db call sites in this repo look like "nothing to report" for months
        while they had never once worked.

        A handler that RAISES, or that CONTINUES or BREAKS a loop, is not that.
        It has made an explicit decision about control flow, and there is no
        `return` it could add: `except OSError: continue` inside a loop cannot be
        rewritten to satisfy a return-only rule without changing what it does. So
        those were violations no one could act on, which is how a rule with 3,276
        hits becomes something readers skip past.

        What still counts: a handler whose body neither returns, raises, nor
        redirects the loop — `pass`, or a bare log-and-fall-through.
        """
        _HANDLED = (ast.Return, ast.Raise, ast.Continue, ast.Break)
        for handler in try_node.handlers:
            has_return = any(isinstance(stmt, _HANDLED) for stmt in handler.body)

            if not has_return:
                self.violations.append(ConventionViolation(
                    self.filepath, handler.lineno, 'FAIL_SOFT_ERROR',
                    'Exception handler should return a sensible default (empty string, None, etc.)'
                ))

    def _check_unguarded_mutations(self, node: ast.Attribute) -> None:
        """Flag mutations to shared state outside lock context."""
        pass

    def _check_hardcoded_secrets(self, node: ast.Assign) -> None:
        """Check for hardcoded secrets in variables with sensitive names.

        A literal that is the SOURCE OF A PATTERN is excluded (see
        _is_regex_source): this rule keys off the target name alone, so a regex
        written to FIND credentials satisfies it by construction and every
        secret scanner in this repo reported its own detector as a hardcoded
        secret. The rule punished exactly the code written to enforce it.
        """
        secret_keywords = ('password', 'token', 'secret', 'key', 'api_key')

        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            if _is_regex_source(node.value.value):
                return
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


#: Per-rule counts that are already in the tree. The hook fails when a count RISES.
BASELINE_PATH = Path(__file__).resolve().parent.parent / ".convention-lint-baseline.json"


def load_baseline(path=None):
    """Grandfathered per-rule counts. Missing/corrupt file reads as an empty baseline.

    Empty means "nothing is grandfathered", which is the strict direction — a corrupt
    baseline must not silently disable the gate.
    """
    target = Path(path or BASELINE_PATH)
    try:
        with open(target, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    counts = data.get("counts") if isinstance(data, dict) else None
    return {k: int(v) for k, v in (counts or {}).items() if isinstance(v, (int, float))}


def count_by_rule(violations):
    counts = {}
    for violation in violations:
        counts[violation.rule] = counts.get(violation.rule, 0) + 1
    return counts


def regressions(counts, baseline):
    """Rules whose count exceeds the baseline. Sorted for a stable report."""
    out = []
    for rule, count in sorted(counts.items()):
        allowed = baseline.get(rule, 0)
        if count > allowed:
            out.append((rule, count, allowed))
    return out


def write_baseline(counts, path=None):
    target = Path(path or BASELINE_PATH)
    payload = {
        "_comment": (
            "Grandfathered convention-lint counts, from a whole-tree scan of "
            "`runner tools scripts`. The hook fails only when a rule's count RISES above "
            "these numbers, so the gate is enforceable today without a repo-wide cleanup "
            "patch. Lower these as violations are fixed; never raise one to make a commit "
            "pass. Regenerate with: python tools/lint_conventions.py --update-baseline "
            "runner tools scripts"
        ),
        "counts": {k: int(v) for k, v in sorted(counts.items())},
        "total": int(sum(counts.values())),
    }
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
        fh.write("\n")
    return payload


def main():
    """Main entry point for the linter.

    RATCHET, not a cliff. A bare `exit(1) if any violations` gate is unusable here: the
    tree carries thousands of pre-existing violations, so the pre-commit hook failed on
    every commit and the only way to work was `--no-verify` — which disables every OTHER
    hook too. A gate that is always red is not a gate.

    So the hook fails when a rule's count RISES above the recorded baseline: existing
    violations are visible, counted, and can only go down. Same shape as the repo's
    .tsc-error-baseline ratchet.

    This only holds for a WHOLE-TREE scan, because the baseline holds whole-tree totals.
    Invoked on a subset of files — which is what `pass_filenames: true` in
    .pre-commit-config.yaml does today — the comparison is vacuous and every run passes;
    that path prints a NOTE saying so instead of a green OK.

    `--update-baseline` rewrites the file (use after fixing violations, or when adding a
    rule). `--strict` ignores the baseline entirely, for a full audit.
    """
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = {a for a in sys.argv[1:] if a.startswith("-")}
    if not args:
        print("Usage: python lint_conventions.py [--strict|--update-baseline] "
              "<file_or_dir> [...]", file=sys.stderr)
        sys.exit(1)

    all_violations = []
    scanned_a_directory = False

    for target in args:
        target_path = Path(target).resolve()
        if target_path.is_file():
            all_violations.extend(check_file(str(target_path)))
        elif target_path.is_dir():
            scanned_a_directory = True
            all_violations.extend(scan_directory(str(target_path)))
        else:
            print(f"Warning: {target} is not a file or directory", file=sys.stderr)

    all_violations.sort(key=lambda v: (v.filepath, v.lineno))
    counts = count_by_rule(all_violations)

    if "--update-baseline" in flags:
        payload = write_baseline(counts)
        print(f"convention-lint: baseline written ({payload['total']} violations across "
              f"{len(payload['counts'])} rules) -> {BASELINE_PATH.name}")
        sys.exit(0)

    if "--strict" in flags:
        for violation in all_violations:
            print(str(violation))
        sys.exit(1 if all_violations else 0)

    baseline = load_baseline()

    # The baseline holds WHOLE-TREE totals, so it can only be compared against a
    # whole-tree scan. .pre-commit-config.yaml sets `pass_filenames: true`, which means
    # the hook invokes this with just the staged files — a handful of violations
    # compared against a five-thousand ceiling, so it can never regress and the gate
    # has been passing unconditionally. A brand-new file containing nothing but a
    # silent `except: pass` is reported as "grandfathered" and exits 0. Say so rather
    # than printing a reassuring OK: an invisible no-op gate is worse than no gate,
    # because people believe it. The fix is `pass_filenames: false` with fixed targets
    # (`runner tools scripts`) in the hook, which is what this scan is baselined on.
    if baseline and not scanned_a_directory:
        print("convention-lint: NOTE — ratchet skipped. The baseline is a whole-tree "
              "count and this run only saw the files passed to it, so nothing can "
              "exceed it. Run `python tools/lint_conventions.py runner tools scripts` "
              "for the real gate.", file=sys.stderr)

    over = regressions(counts, baseline)
    if over:
        # Print only the offending rules' violations: a full several-thousand-line dump
        # buries the handful of lines the author actually needs to fix.
        offending = {rule for rule, _c, _a in over}
        for violation in all_violations:
            if violation.rule in offending:
                print(str(violation))
        print("", file=sys.stderr)
        for rule, count, allowed in over:
            print(f"convention-lint: {rule} rose to {count} (baseline {allowed})",
                  file=sys.stderr)
        print("convention-lint: fix the new violations, or run with --update-baseline "
              "ONLY after genuinely reducing a count.", file=sys.stderr)
        sys.exit(1)

    total = sum(counts.values())
    if total:
        print(f"convention-lint: OK — {total} grandfathered violation(s), none new.")
    sys.exit(0)


if __name__ == '__main__':
    main()
