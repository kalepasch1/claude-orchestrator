"""Narrow proof for the CLASS_NAMING convention rule.

Accepts the class spellings CLAUDE.md prescribes (PascalCase, incl. acronym-led and
private-prefixed), rejects the ones it forbids (snake_case, lowercase, SCREAMING_CASE).
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from convention_lint import check_file, _is_pascal_case  # noqa: E402


class TestPascalCasePredicate(unittest.TestCase):
    """The predicate on its own — no file IO, no AST."""

    def test_accepts_valid_class_names(self):
        for name in ('ConventionChecker', 'HTTPClient', 'DBPool', 'Sha256Digest',
                     '_PrivateCache', 'T', 'Foo2'):
            self.assertTrue(_is_pascal_case(name), f'{name!r} should be accepted')

    def test_rejects_invalid_class_names(self):
        for name in ('my_class', 'lowercase', 'MY_CLASS', 'Convention_Checker',
                     '__dunder__', '9Lives', ''):
            self.assertFalse(_is_pascal_case(name), f'{name!r} should be rejected')

    def test_fail_soft_on_non_string_input(self):
        # Repo convention: a public-facing predicate must not raise on bad input.
        self.assertFalse(_is_pascal_case(None))
        self.assertFalse(_is_pascal_case(123))


class TestClassNamingRule(unittest.TestCase):
    """The rule as the linter reports it, end to end through check_file."""

    def _class_naming_violations(self, code):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            path = f.name
        try:
            return [v for v in check_file(path) if v.rule == 'CLASS_NAMING']
        finally:
            os.unlink(path)

    def test_valid_class_name_produces_no_violation(self):
        self.assertEqual(self._class_naming_violations(
            'class ConventionChecker:\n    pass\n'), [])

    def test_snake_case_class_name_is_flagged(self):
        violations = self._class_naming_violations('class my_class:\n    pass\n')
        self.assertEqual(len(violations), 1)
        self.assertIn('my_class', violations[0].message)
        self.assertEqual(violations[0].severity, 'warning')
        self.assertEqual(violations[0].lineno, 1)

    def test_nested_class_is_checked_too(self):
        violations = self._class_naming_violations(
            'class Outer:\n    class inner_thing:\n        pass\n')
        self.assertEqual([v.message.split("'")[1] for v in violations], ['inner_thing'])

    def test_unparseable_file_reports_syntax_error_not_a_naming_violation(self):
        # The rule must not manufacture naming findings out of a file it never parsed.
        self.assertEqual(self._class_naming_violations('class my_class(\n'), [])


if __name__ == '__main__':
    unittest.main()
