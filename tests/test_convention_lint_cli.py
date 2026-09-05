"""CLI-level behaviour of tools/convention_lint.py.

The rule checks are covered elsewhere. What is covered here is the part that decides
whether the gate actually gates: a path that does not exist, the default path list, and
the severity spelling the exit code keys off. Each of these had a shape where the linter
could report success without having checked anything.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tools.convention_lint import (  # noqa: E402
    DEFAULT_CHECK_PATHS,
    ConventionViolation,
    is_blocking,
    main,
)


class TestSeverityGate(unittest.TestCase):
    def test_error_blocks(self):
        self.assertTrue(is_blocking('error'))

    def test_warn_and_warning_do_not_block(self):
        self.assertFalse(is_blocking('warn'))
        self.assertFalse(is_blocking('warning'))
        self.assertFalse(is_blocking('WARNING'))

    def test_unknown_severity_blocks(self):
        # Fail closed: an unrecognised spelling must not silently stop gating.
        self.assertTrue(is_blocking('nitpick'))
        self.assertTrue(is_blocking(''))
        self.assertTrue(is_blocking(None))


class TestMissingPath(unittest.TestCase):
    def _run(self, argv):
        with mock.patch.object(sys, 'argv', argv):
            return main()

    def test_nonexistent_path_is_reported_and_fails(self):
        code = self._run(['convention_lint.py', 'no/such/directory'])
        self.assertEqual(code, 1, 'a typoed path must not pass by checking nothing')

    def test_nonexistent_path_appears_in_json_output(self):
        with mock.patch('builtins.print') as printed:
            self._run(['convention_lint.py', '--json', 'no/such/directory'])
        payload = ''.join(str(call.args[0]) for call in printed.call_args_list if call.args)
        self.assertIn('MISSING_PATH', payload)

    def test_clean_existing_file_still_passes(self):
        here = os.path.dirname(os.path.abspath(__file__))
        target = os.path.join(here, 'fixture_clean_module.py')
        with open(target, 'w', encoding='utf-8') as handle:
            handle.write('def value():\n    return 1\n')
        try:
            self.assertEqual(self._run(['convention_lint.py', target]), 0)
        finally:
            os.remove(target)


class TestDefaults(unittest.TestCase):
    def test_default_paths_are_immutable(self):
        # A mutable default was extended in place by --check-path, so a second run in the
        # same process inherited paths the caller never asked for.
        self.assertIsInstance(DEFAULT_CHECK_PATHS, tuple)
        self.assertEqual(DEFAULT_CHECK_PATHS, ('runner', 'tools'))

    def test_violation_defaults_to_error(self):
        self.assertEqual(ConventionViolation('f.py', 1, 'R', 'm').severity, 'error')


if __name__ == '__main__':
    unittest.main()
