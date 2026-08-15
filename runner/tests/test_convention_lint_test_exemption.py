"""The convention linter must not flag test files for doing their job.

MEASURED before this change: 246 violations, 178 of them (72%) inside test files. A test
that asserts a function raises has to contain a raise; a fixture named `secret` is a
fixture, not a credential.

That is not a cosmetic complaint. tools/convention_lint.py is a pre-commit hook that exits
1, so a mostly-false report does not make the gate strict — it makes it something everyone
routes around with --no-verify, at which point it enforces nothing. Accuracy is the
precondition for enforcement.

The exemption is deliberately narrow: only FAIL_SOFT_ERROR and HARDCODED_SECRET, only in
test files. A real singleton bug hiding in a test module is still a real bug.
"""
import os
import sys
import tempfile
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "tools"))

import convention_lint as cl  # noqa: E402

RAISES = '''
def helper(x):
    if not x:
        raise ValueError("bad input")
    return x
'''

SECRETS = '''
secret = "hunter2"
api_token = "abc123"
'''


class IsTestFileTest(unittest.TestCase):
    def test_prefixed_module(self):
        self.assertTrue(cl.is_test_file("runner/test_thing.py"))

    def test_tests_directory(self):
        self.assertTrue(cl.is_test_file("runner/tests/anything.py"))

    def test_suffixed_module(self):
        self.assertTrue(cl.is_test_file("runner/thing_test.py"))

    def test_windows_separators(self):
        self.assertTrue(cl.is_test_file(r"runner\\tests\\thing.py"))

    def test_production_module_is_not_a_test(self):
        self.assertFalse(cl.is_test_file("runner/merge_train.py"))

    def test_a_name_merely_containing_test_is_not_a_test(self):
        # `latest_run.py` and `contest.py` must not be exempted by accident
        self.assertFalse(cl.is_test_file("runner/latest_run.py"))
        self.assertFalse(cl.is_test_file("runner/contest.py"))

    def test_none_is_handled(self):
        self.assertFalse(cl.is_test_file(None))


class ExemptionTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _check(self, name, source):
        path = os.path.join(self.tmp.name, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(source)
        return {v.rule for v in cl.check_file(path)}

    def test_a_raise_in_production_code_is_still_reported(self):
        self.assertIn("FAIL_SOFT_ERROR", self._check("prod.py", RAISES))

    def test_a_raise_in_a_test_is_not_reported(self):
        self.assertNotIn("FAIL_SOFT_ERROR", self._check("test_prod.py", RAISES))

    def test_a_raise_in_a_tests_directory_is_not_reported(self):
        self.assertNotIn("FAIL_SOFT_ERROR", self._check("tests/prod.py", RAISES))

    def test_a_secret_in_production_code_is_still_reported(self):
        self.assertIn("HARDCODED_SECRET", self._check("prod.py", SECRETS))

    def test_a_fixture_named_secret_in_a_test_is_not_reported(self):
        self.assertNotIn("HARDCODED_SECRET", self._check("test_prod.py", SECRETS))

    def test_the_exemption_list_is_narrow(self):
        # widening this silently would re-open the hole the noise came through
        self.assertEqual(cl.TEST_EXEMPT_RULES,
                         frozenset({"FAIL_SOFT_ERROR", "HARDCODED_SECRET"}))

    def test_syntax_errors_are_reported_even_in_tests(self):
        # a test file that cannot be parsed is broken, not exempt
        self.assertIn("SYNTAX_ERROR", self._check("test_broken.py", "def f(\n"))


class ChokePointTest(unittest.TestCase):
    """Rules must report through _record, or a new rule reintroduces the noise."""

    def _source(self):
        with open(os.path.join(_REPO, "tools", "convention_lint.py")) as fh:
            return fh.read()

    def test_no_rule_appends_directly(self):
        body = self._source().split("class ConventionChecker", 1)[1]
        self.assertNotIn("self.violations.append(ConventionViolation(", body)

    def test_every_rule_goes_through_the_gate(self):
        self.assertGreaterEqual(
            self._source().count("self._record(ConventionViolation("), 4)


class RealRepoTest(unittest.TestCase):
    """The point of the change: the gate is now mostly signal."""

    def test_no_exempt_rule_fires_in_any_test_file_of_this_repo(self):
        offenders = []
        for directory in ("runner", "tools"):
            path = os.path.join(_REPO, directory)
            if not os.path.isdir(path):
                continue
            for v in cl.check_directory(path):
                if cl.is_test_file(v.filepath) and v.rule in cl.TEST_EXEMPT_RULES:
                    offenders.append(str(v))
        self.assertEqual(offenders[:5], [], f"{len(offenders)} exempt-rule hits in tests")


if __name__ == "__main__":
    unittest.main()
