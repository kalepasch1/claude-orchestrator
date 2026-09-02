#!/usr/bin/env python3
"""The convention linter's RULE SET, pinned so a rule cannot vanish unnoticed.

OWNER MODULE. `tools/lint_conventions.py` is the linter the pre-commit hook actually
invokes (.pre-commit-config.yaml `entry: python tools/lint_conventions.py`), so it is the
only copy whose behaviour can block a commit. Three other near-identical linters exist and
are wired to nothing — see CONVENTION_LINT.md — which is precisely why "which rules are we
enforcing?" needs an executable answer rather than a reading of whichever file you opened.

WHAT THIS CATCHES. A rule can disappear two ways, and neither shows up as a test failure
anywhere else: someone deletes the check, or someone edits the `if` that reaches it so it
can never fire. The existing baseline ratchet (.convention-lint-baseline.json) counts
VIOLATIONS, so it happily goes green when a rule stops firing — a removed rule looks
exactly like a fixed codebase. This pins the rule NAMES and proves each one still fires on
a fixture that violates it.

Deliberately not a golden-file snapshot: adding a rule should be a one-line edit here with
a reason, not a blind `--update-snapshot`.
"""
import ast
import importlib.util
import os
import re
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_linter(module_path, module_name):
    """Load the hook's linter from its path, WITHOUT touching sys.path/sys.modules.

    This file used to do `sys.path.insert(REPO/tools)` + `import lint_conventions`,
    and the repo has a SECOND module of that name at runner/tools/. sys.path is
    process-global under pytest, and -- the part that is easy to miss -- a
    `from lint_conventions import <name that does not exist>` still leaves the
    module it loaded in sys.modules even though the import statement raised.
    test_convention_conformance_comprehensive.py does exactly that with
    runner/tools' copy, so by the time this file ran, `import lint_conventions`
    was a cache hit on the OTHER linter and the rule fixtures below were being
    checked against rules this file does not own. Alone it passed; after that
    file, test_magic_numbers_fires failed.

    Same loader, same reasoning, as test_convention_lint_ratchet.py and
    test_annotated_secret_detection.py.
    """
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint_conventions = _load_linter(os.path.join(REPO, "tools", "lint_conventions.py"),
                                "tools_lint_conventions_rule_registry")

#: Every rule the canonical linter is expected to emit. Adding one here without adding the
#: check (or vice versa) fails, so the registry and the implementation cannot drift apart.
EXPECTED_RULES = {
    "CONFIG_KEY_NAMING",
    "FAIL_SOFT_ERROR",
    "HARDCODED_SECRET",
    "MAGIC_NUMBERS",
    "MODULE_SINGLETON",
    "NAMING_CONVENTION",
    # Reported for files the linter cannot read; they are rules in the same sense — their
    # loss would silently turn an unparseable file into a clean one.
    "PARSE_ERROR",
    "SYNTAX_ERROR",
}


def emitted_rule_names():
    """Rule strings the module actually constructs, read from its source."""
    source = open(os.path.join(REPO, "tools", "lint_conventions.py"), encoding="utf-8").read()
    return set(re.findall(r"ConventionViolation\(\s*[^,]+,\s*[^,]+,\s*'([A-Z_]+)'", source))


def check(code, filename="probe.py"):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(code)
        path = fh.name
    try:
        return {v.rule for v in lint_conventions.check_file(path)}
    finally:
        os.unlink(path)


class TestRuleRegistry(unittest.TestCase):
    def test_no_rule_has_been_removed(self):
        missing = EXPECTED_RULES - emitted_rule_names()
        self.assertEqual(missing, set(),
                         f"rule(s) no longer emitted by the linter: {sorted(missing)}. "
                         f"If the removal was deliberate, delete them from EXPECTED_RULES "
                         f"in this file with a reason.")

    def test_no_rule_has_been_added_without_registering_it(self):
        extra = emitted_rule_names() - EXPECTED_RULES
        self.assertEqual(extra, set(),
                         f"new rule(s) {sorted(extra)} are emitted but not registered here. "
                         f"Add them to EXPECTED_RULES and to the baseline via "
                         f"`python tools/lint_conventions.py --update-baseline runner tools`.")

    def test_the_count_is_pinned_too(self):
        # A same-sized swap (one rule renamed into another) passes both set checks above
        # only if the names match; this makes an accidental net change loud.
        self.assertEqual(len(EXPECTED_RULES), 8)


class TestEachRuleStillFires(unittest.TestCase):
    """A registered rule that can no longer fire is removed in all but name."""

    def test_fail_soft_error_fires(self):
        self.assertIn("FAIL_SOFT_ERROR",
                      check("def f():\n    try:\n        g()\n    except Exception:\n        pass\n"))

    def test_hardcoded_secret_fires(self):
        self.assertIn("HARDCODED_SECRET", check("api_key = 'literal-value-here'\n"))

    def test_syntax_error_fires(self):
        self.assertIn("SYNTAX_ERROR", check("def broken(:\n"))

    def test_magic_numbers_fires(self):
        self.assertIn("MAGIC_NUMBERS", check("def f():\n    return 86400\n"))

    def test_naming_convention_fires(self):
        self.assertIn("NAMING_CONVENTION", check("def BadlyNamedFunction():\n    return 1\n"))

    def test_a_clean_file_trips_nothing(self):
        # The other half of the guarantee: rules that fire on everything are worthless.
        clean = ('"""Docstring."""\n'
                 'import os\n\n\n'
                 'def read_value(name):\n'
                 '    """Return an env value, empty string when unset."""\n'
                 '    try:\n'
                 '        return os.environ.get(name, "")\n'
                 '    except Exception as exc:\n'
                 '        print(exc)\n'
                 '        return ""\n')
        self.assertEqual(check(clean) & {"FAIL_SOFT_ERROR", "SYNTAX_ERROR", "PARSE_ERROR"}, set())


class TestOwnerModuleIsStillTheWiredOne(unittest.TestCase):
    def test_the_pre_commit_hook_still_points_at_this_linter(self):
        """If the hook is repointed, this registry is guarding the wrong file."""
        config = open(os.path.join(REPO, ".pre-commit-config.yaml"), encoding="utf-8").read()
        self.assertIn("tools/lint_conventions.py", config,
                      "the pre-commit hook no longer runs tools/lint_conventions.py — "
                      "update this test to guard whichever linter is now canonical")

    def test_check_file_is_the_public_entry_point(self):
        self.assertTrue(callable(getattr(lint_conventions, "check_file", None)))

    def test_module_parses(self):
        # Cheap and total: the linter itself must not be the thing with a syntax error.
        ast.parse(open(os.path.join(REPO, "tools", "lint_conventions.py"), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
