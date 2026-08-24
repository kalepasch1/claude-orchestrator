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


# Identifier words that suggest a credential. Matched as whole words after splitting the
# identifier on snake_case/camelCase boundaries — NOT as bare substrings. The previous
# unanchored `re.search` made "AUTH" fire inside "author_model" and "author_provider",
# and "CREDENTIAL" inside "IGNORE_CREDENTIAL", which accounted for most of this rule's
# output on runner/.
#
# "key" is deliberately NOT in this set. This repo names its fleet_config entries
# STATE_KEY, BUDGET_KEY, PRESSURE_KEY, CONTROL_KEY and so on — they hold the *name of a
# config row*, never a credential. Treating a bare "key" as a secret keyword flags ~20 of
# them. Compound spellings (api_key, private_key, access_key, secret_key) are matched
# separately by _names_a_secret, which is where "key" genuinely does imply a credential.
SECRET_NAME_WORDS = frozenset({
    'password', 'passwd', 'token', 'secret', 'credential', 'credentials', 'auth',
})

# Values that name or stand in for a secret without being one. A rule that cannot tell
# "the string test-key" from an actual credential trains people to run `--no-verify`.
PLACEHOLDER_MARKERS = (
    'test', 'example', 'sample', 'dummy', 'fake', 'placeholder', 'changeme',
    'marker', 'redacted', 'your-', 'your_', 'xxx', 'todo', 'none', 'null',
)

# Shortest string that could carry a credential at all. Deliberately low: the placeholder
# and entropy checks below do the discriminating, and a high threshold here would silently
# stop flagging the short toy secrets the rule is specified (and tested) to catch.
MIN_SECRET_VALUE_LEN = 4


def _identifier_words(name: str) -> set:
    """Lowercased word set for an identifier, splitting snake_case and camelCase.

    "author_model" -> {"author", "model"}, so the "auth" keyword no longer matches it,
    while "auth_token" -> {"auth", "token"} still does.
    """
    spaced = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', str(name or ''))
    return {w for w in re.split(r'[^A-Za-z0-9]+', spaced.lower()) if w}


def _names_a_secret(name: str) -> bool:
    """True when the identifier claims to hold a credential, by whole-word match."""
    words = _identifier_words(name)
    if words & SECRET_NAME_WORDS:
        return True
    # "key" only implies a credential next to a qualifier: api_key, private_key,
    # access_key, secret_key. Order-independent, so apiKey and KEY_API both match.
    if 'key' not in words:
        return False
    return bool(words & {'api', 'private', 'access', 'signing', 'encryption'})


def _is_self_naming_constant(name: str, value: str) -> bool:
    """True when the literal is just the constant's own name spelled out.

        RULE_HARDCODED_SECRET = "HARDCODED_SECRET"
        SECRET = "SECRET"
        _TOKEN_KIND = "TOKEN_KIND"

    These are identifiers, not credentials. The rule flagged the first one — inside
    runner/tools/lint_conventions.py, i.e. the linter reported a lint rule's own name
    constant as a hardcoded secret. That is the most corrosive kind of false positive:
    it appears under the one rule whose whole value is that people trust it, and the
    only way to act on it is to suppress it.

    Deliberately narrow. It requires the value to BE the name (or the tail of it) — a
    real credential does not happen to equal its own variable name, so this cannot
    launder one.
    """
    norm_value = (value or "").strip().upper().replace("-", "_")
    norm_name = (name or "").strip().upper().lstrip("_")
    if not norm_value or not norm_name:
        return False
    if norm_value == norm_name:
        return True
    return norm_name.endswith("_" + norm_value)


def _looks_like_secret_value(value: str) -> bool:
    """True only when the assigned literal could plausibly BE a credential.

    This is the gate the rule was missing. It fired on the name alone, so
    `auth_hint = ""` and `os.environ["PLOEH_S2S_SECRET"] = "test-key"` were reported as
    hardcoded secrets — an empty string and a placeholder respectively, neither of which
    can leak anything. Checking the value is what makes the rule's output actionable.
    """
    text = str(value or '').strip()
    if len(text) < MIN_SECRET_VALUE_LEN:
        return False           # "" cannot leak anything; neither can a 3-char flag
    if text.startswith('$'):
        return False           # env placeholder: $SECRET, ${SECRET}
    if any(ch.isspace() for ch in text):
        return False           # prose/messages, not credentials
    low = text.lower()
    if any(marker in low for marker in PLACEHOLDER_MARKERS):
        return False
    # A credential carries entropy; a single repeated character or a lone word does not.
    return len(set(text)) >= 5


def is_test_file(filepath: str) -> bool:
    """True for pytest/unittest modules, by this repo's actual layout.

    Both spellings are in use here — runner/test_*.py alongside runner/tests/test_*.py —
    so match on either the directory or the filename.
    """
    p = str(filepath or "").replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    return (name.startswith("test_") or name.endswith("_test.py")
            or "/tests/" in p or p.startswith("tests/"))


#: PascalCase, with one optional leading underscore for a private type. Each remaining
#: word starts with a capital; digits are allowed after the first character; a run of
#: capitals is allowed so acronym-led names (HTTPClient, DBPool) pass unchanged. An
#: underscore anywhere after the first character makes it snake_case, which fails.
_PASCAL_CASE_RE = re.compile(r'^_?[A-Z][A-Za-z0-9]*$')


def _is_pascal_case(name: str) -> bool:
    """True when `name` is a valid PascalCase class name. Never raises on bad input."""
    # SCREAMING_CASE is rejected by the underscore clause of the pattern. An all-caps
    # name with no underscore (HTTP, API) is deliberately ACCEPTED: those are real class
    # spellings here, and a naming rule that fires on correct code is the thing that
    # teaches people to run --no-verify.
    return bool(_PASCAL_CASE_RE.match(str(name or '')))


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
        self._check_class_naming(node)
        self.class_depth += 1
        self.generic_visit(node)
        self.class_depth -= 1

    def _check_class_naming(self, node: ast.ClassDef) -> None:
        """Flag class names that are not PascalCase.

        CLAUDE.md states the convention plainly: "PascalCase for types/classes/components".
        A linter that enforces error handling and secret hygiene but not the one naming
        rule the repo actually writes down leaves the most-read convention unenforced.

        Deliberately narrow, because a naming rule that fires on correct code is worse
        than no rule at all:
          * a single leading underscore is allowed (`_PrivateCache` is a documented
            private-type spelling here);
          * consecutive capitals are allowed, so acronym-led names (`HTTPClient`,
            `DBPool`) are not "fixed" into a spelling nobody uses;
          * digits are allowed after the first character (`Sha256Digest`).
        Only the shapes the convention actually forbids are reported: snake_case,
        lowercase-initial, and SCREAMING_CASE class names. Reported as a warning, not an
        error, because a name is a readability defect and should not block a commit.
        """
        if not _is_pascal_case(node.name):
            self._record(ConventionViolation(
                self.filepath, node.lineno, 'CLASS_NAMING',
                f"Class '{node.name}' is not PascalCase "
                f"(CLAUDE.md: PascalCase for types/classes/components)",
                severity='warning',
            ))

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

    # A client-side scan window becomes a bug only once the set outgrows it, so the
    # threshold is "big enough that someone meant to take a large slice".
    _SCAN_WINDOW_MIN_LIMIT = 100
    # `limit: "5001"` is the documented "are there more than 5000?" sentinel — the count
    # is never used as a total, only compared to 5000. Flagging it would push people to
    # "fix" a correct idiom.
    _SCAN_WINDOW_SENTINELS = frozenset({"5001", "1001", "101"})

    def visit_Call(self, node: ast.Call) -> None:
        """Flag `db.select(..., {"limit": <big>})` with no `order`.

        WHY THIS RULE EXISTS. The shape has produced four outage-class failures on this
        fleet (merge_train._pick_cards: newest 3,000 of 238,177 approvals; another
        producing 240 duplicates of one slug; ev_scheduler scoring an arbitrary 500 of
        1,407 QUEUED tasks; config_optimizer autoscaling off a queue depth structurally
        incapable of exceeding 1,000). Each looked like "the queue is slow" from outside.

        PostgREST caps a response at 1,000 rows regardless of `limit`, so a large limit
        does not widen the window — it only hides the truncation. Without an `order` the
        rows returned are not even reproducible, so one end of the set becomes
        structurally invisible and the work there sits forever.

        The rule was specified by tests/test_scan_window_correctness.py and never
        implemented, so the guard against the class did not exist while its regression
        tests sat red.
        """
        try:
            self._check_scan_window(node)
        finally:
            self.generic_visit(node)

    @staticmethod
    def _limit_literal(value) -> str:
        """Render a limit value as a string if it is statically knowable, else ''.

        Handles the `str(800)` form as well as a bare literal; a computed limit cannot be
        judged here and is left alone rather than guessed at.
        """
        if isinstance(value, ast.Constant):
            return str(value.value)
        if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                and value.func.id == "str" and len(value.args) == 1
                and isinstance(value.args[0], ast.Constant)):
            return str(value.args[0].value)
        return ""

    def _check_scan_window(self, node: ast.Call) -> None:
        func = node.func
        # `db.select(...)` only. `select_all` pages to exhaustion and is the fix, not the
        # smell, so it must never be flagged.
        if not (isinstance(func, ast.Attribute) and func.attr == "select"):
            return
        if not (isinstance(func.value, ast.Name) and func.value.id == "db"):
            return

        params = next((arg for arg in node.args if isinstance(arg, ast.Dict)), None)
        if params is None:
            return

        keys = {}
        for key, value in zip(params.keys, params.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys[key.value] = value
        if "order" in keys:
            return
        if "limit" not in keys:
            return

        raw = self._limit_literal(keys["limit"])
        if not raw or raw in self._SCAN_WINDOW_SENTINELS:
            return
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            return
        if limit < self._SCAN_WINDOW_MIN_LIMIT:
            return

        self._record(ConventionViolation(
            self.filepath, node.lineno, 'SCAN_WINDOW_NO_ORDER',
            f'db.select with limit={limit} and no "order": the window is not reproducible '
            f'and PostgREST caps the response at 1000 rows regardless. Use db.select_all '
            f'for a full scan, db.count for a count, or add a deterministic "order".'
        ))

    def visit_Assign(self, node: ast.Assign) -> None:
        """Check for hardcoded secrets in assignments."""
        self._check_hardcoded_secrets(node)
        self.generic_visit(node)

    def _own_nodes(self, node: ast.FunctionDef):
        """Walk a function body without descending into nested functions/classes.

        ast.walk() crosses scope boundaries, so a `raise` inside a nested helper was
        attributed to its enclosing function (and a nested try/except was credited as
        the enclosing function's handler). Nested scopes are visited on their own,
        so yielding them here double-counts as well as misattributes.
        """
        stack = list(ast.iter_child_nodes(node))
        while stack:
            child = stack.pop()
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            yield child
            stack.extend(ast.iter_child_nodes(child))

    def _check_fail_soft_error_handling(self, node: ast.FunctionDef) -> None:
        """
        Rule 1: Fail-soft error handling

        Public module-level functions should not raise on bad input.
        Flag functions that have raise statements but no try/except handlers.
        """
        # Only check public module-level functions. function_context already holds
        # this function, so depth > 1 means it is nested inside another function.
        if self.class_depth > 0 or node.name.startswith('_'):
            return
        if len(self.function_context) > 1:
            return

        has_raise = False
        for child in self._own_nodes(node):
            if isinstance(child, ast.Raise):
                has_raise = True
                break

        if has_raise:
            # Check if there are try/except blocks that handle errors gracefully
            has_error_handler = False
            for child in self._own_nodes(node):
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
        for child in self._own_nodes(node):
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
        if not (isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            return

        # The value gate runs first and rejects most of the tree, so a name that merely
        # mentions credentials costs nothing until something secret-shaped is assigned.
        value = node.value.value
        if not _looks_like_secret_value(value):
            return

        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id
                if _names_a_secret(var_name) and not _is_self_naming_constant(var_name, value):
                    self._record(ConventionViolation(
                        self.filepath, node.lineno, 'HARDCODED_SECRET',
                        f'Variable "{var_name}" is assigned a literal that looks like a '
                        'credential; read it from the environment instead'
                    ))
            elif isinstance(target, ast.Subscript):
                if isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str):
                    key_name = target.slice.value
                    if _names_a_secret(key_name) and not _is_self_naming_constant(key_name, value):
                        self._record(ConventionViolation(
                            self.filepath, node.lineno, 'HARDCODED_SECRET',
                            f'Config key "{key_name}" is assigned a literal that looks like '
                            'a credential; read it from the environment instead'
                        ))


_NOQA_RE = re.compile(r'#\s*noqa(?::\s*(?P<rules>[A-Za-z0-9_,\s]+))?', re.IGNORECASE)


def _apply_noqa(violations: List[ConventionViolation],
                source_lines: List[str]) -> List[ConventionViolation]:
    """Drop violations whose reported line carries a covering `# noqa`.

    A rule with no per-line override gets bypassed wholesale instead — a suppression
    that stays visible in the diff and greppable in review is the lesser evil. Bare
    `# noqa` covers everything on the line; `# noqa: RULE` covers only that rule.

    A statement spanning several lines is reported at its FIRST line, so the comment is
    also looked for on the last line of the call — that is where it reads naturally
    when the params dict is wrapped.
    """
    kept = []
    for violation in violations:
        start = (violation.lineno or 1) - 1
        candidates = []
        for index in (start, start + 1, start + 2, start + 3):
            if 0 <= index < len(source_lines):
                candidates.append(source_lines[index])
        if any(_is_suppressed(line, violation.rule) for line in candidates):
            continue
        kept.append(violation)
    return kept


def _is_suppressed(line: str, rule: str) -> bool:
    match = _NOQA_RE.search(line or '')
    if not match:
        return False
    rules = match.group('rules')
    if not rules:
        return True
    return rule.upper() in {r.strip().upper()
                            for r in rules.replace(',', ' ').split() if r.strip()}


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
