"""Narrow regression coverage for the CLASS_NAMING convention lint.

Before this rule existed the checker held functions to snake_case but never looked at
class names at all, so `class taskRunner:` reached review unflagged. These tests pin
both halves of the contract: the rule fires on a real style break, and it stays quiet
on the shapes that are legitimately PascalCase.
"""

import os
import sys
import tempfile
import unittest
from typing import List

# Load runner/tools/lint_conventions.py BY PATH, under an alias.
#
# `lint_conventions` names two different files here — tools/lint_conventions.py (the
# pre-commit ratchet) and runner/tools/lint_conventions.py (this one). A plain import
# resolves to whichever directory reached sys.path first and then serves that from
# sys.modules to every later importer in the same pytest process, so this module and
# test_convention_lint_ratchet.py silently fought over the name: running them together
# failed 10 tests that each passed alone, in whichever order lost. Importing by path
# makes each test say which file it means.
import importlib.util  # noqa: E402

_LINT_CONVENTIONS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'lint_conventions.py')
_spec = importlib.util.spec_from_file_location(
    '_runner_lint_conventions', os.path.normpath(_LINT_CONVENTIONS_PATH))
_runner_lint_conventions = importlib.util.module_from_spec(_spec)
sys.modules['_runner_lint_conventions'] = _runner_lint_conventions
_spec.loader.exec_module(_runner_lint_conventions)

ConventionViolation = _runner_lint_conventions.ConventionViolation
check_file = _runner_lint_conventions.check_file


class ClassNamingLintTest(unittest.TestCase):
    def _check(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as fh:
            fh.write(code)
            fh.flush()
            path = fh.name
        try:
            return check_file(path)
        finally:
            os.unlink(path)

    def _class_naming(self, code: str) -> List[ConventionViolation]:
        return [v for v in self._check(code) if v.rule == 'CLASS_NAMING']

    def test_flags_lower_camel_class_name(self):
        violations = self._class_naming("class taskRunner:\n    pass\n")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].severity, 'warning')
        self.assertIn('taskRunner', violations[0].message)
        self.assertEqual(violations[0].lineno, 1)

    def test_flags_snake_case_class_name(self):
        violations = self._class_naming("class task_runner:\n    pass\n")
        self.assertEqual(len(violations), 1)
        self.assertIn('task_runner', violations[0].message)

    def test_accepts_pascal_case_acronyms_and_digits(self):
        code = (
            "class Runner:\n    pass\n\n"
            "class HTTPClient:\n    pass\n\n"
            "class Rule2Compiler:\n    pass\n"
        )
        self.assertEqual(self._class_naming(code), [])

    def test_ignores_private_class_names(self):
        self.assertEqual(self._class_naming("class _Internal:\n    pass\n"), [])
        self.assertEqual(self._class_naming("class _internal:\n    pass\n"), [])

    def test_severity_is_warning_so_the_merge_train_is_not_newly_blocked(self):
        violations = self._class_naming("class badName:\n    pass\n")
        self.assertTrue(violations)
        self.assertTrue(all(v.severity == 'warning' for v in violations))

    def test_methods_inside_a_class_still_get_function_naming_treatment(self):
        code = "class Runner:\n    def BadMethod(self):\n        pass\n"
        rules = {v.rule for v in self._check(code)}
        self.assertIn('NAMING_CONVENTION', rules)
        self.assertNotIn('CLASS_NAMING', rules)

    def test_nested_class_is_checked(self):
        code = "class Outer:\n    class innerThing:\n        pass\n"
        violations = self._class_naming(code)
        self.assertEqual(len(violations), 1)
        self.assertIn('innerThing', violations[0].message)

    def test_module_level_function_detection_survives_class_traversal(self):
        """visit_ClassDef restores in_module_level, so later module functions still lint."""
        code = (
            "class Runner:\n"
            "    def ok(self):\n"
            "        pass\n"
            "\n"
            "def stray(self):\n"
            "    pass\n"
        )
        rules = {v.rule for v in self._check(code)}
        self.assertIn('MODULE_SINGLETON_PATTERN', rules)


if __name__ == '__main__':
    unittest.main()
