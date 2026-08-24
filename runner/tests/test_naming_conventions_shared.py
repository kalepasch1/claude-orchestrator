"""The two convention linters must share ONE definition of CapWords.

Slices 1-3 of this backlog each added a class-name lint in a different module. Two
reached master with divergent predicates: tools/convention_lint.py accepted
``_PrivateCache`` via its regex, runner/tools/lint_conventions.py rejected it and the
call site patched around that with a separate ``startswith("_")`` test. A contributor
who ran one linter learned a different rule than one who ran the other.

Both now delegate to tools/naming_conventions.is_pascal_case. These tests fail the
moment either grows a private copy again.
"""

import importlib.util
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(REPO, "tools"))

import naming_conventions  # noqa: E402


def _load(alias, *parts):
    """Load a module by PATH, under a unique alias.

    Necessary, and itself a finding: the name ``lint_conventions`` resolves to TWO
    different files in this repo — tools/lint_conventions.py and
    runner/tools/lint_conventions.py — so a plain ``import lint_conventions`` silently
    returns whichever directory landed on sys.path first, and the loser is then served
    from sys.modules to every later importer in the same pytest process. Importing by
    path is the only way to assert something about a specific one of them.
    """
    path = os.path.join(REPO, *parts)
    spec = importlib.util.spec_from_file_location(alias, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


convention_lint = _load("_nc_convention_lint", "tools", "convention_lint.py")
lint_conventions = _load("_nc_lint_conventions", "runner", "tools", "lint_conventions.py")


#: name -> expected verdict. Every edge case the two copies used to disagree on.
CASES = {
    "Runner": True,
    "HTTPClient": True,
    "DBPool": True,
    "Sha256Digest": True,
    "_PrivateCache": True,
    "taskRunner": False,
    "Task_Runner": False,
    "TASK_RUNNER": False,
    "task_runner": False,
    "": False,
    None: False,
}


class CanonicalPredicateTest(unittest.TestCase):

    def test_canonical_verdicts(self):
        for name, expected in CASES.items():
            with self.subTest(name=name):
                self.assertEqual(naming_conventions.is_pascal_case(name), expected)

    def test_is_fail_soft_on_junk(self):
        for junk in (None, 0, 3.5, [], {}, object()):
            self.assertIsInstance(naming_conventions.is_pascal_case(junk), bool)

    def test_message_never_raises(self):
        for name in ("taskRunner", None, 0):
            self.assertIn("PascalCase", naming_conventions.class_naming_message(name))


class BothLintersAgreeTest(unittest.TestCase):
    """The point of the consolidation: no second opinion about the same name."""

    def test_convention_lint_delegates(self):
        self.assertIs(convention_lint._is_pascal_case, naming_conventions.is_pascal_case)

    def test_lint_conventions_delegates(self):
        for name, expected in CASES.items():
            with self.subTest(name=name):
                self.assertEqual(
                    lint_conventions.ConventionChecker._is_pascal_case(name), expected)

    def test_the_two_linters_never_disagree(self):
        for name in CASES:
            with self.subTest(name=name):
                self.assertEqual(
                    convention_lint._is_pascal_case(name),
                    lint_conventions.ConventionChecker._is_pascal_case(name),
                    "the two convention linters disagree about {0!r}".format(name),
                )


if __name__ == "__main__":
    unittest.main()
