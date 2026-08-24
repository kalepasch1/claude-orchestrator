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
        # Widening this silently would re-open the hole the noise came through, so the
        # set is pinned and any change has to come here and say why.
        #
        # MAGIC_NUMBERS added 2026-08-24: 2,052 of its 3,139 findings (65%) were inside
        # test files, where the literal IS the expected value —
        # `assertEqual(cache.limit_bytes, 50000)` becomes a test that a constant equals
        # itself once the number is hoisted. Production literals are still flagged.
        self.assertEqual(cl.TEST_EXEMPT_RULES,
                         frozenset({"FAIL_SOFT_ERROR", "HARDCODED_SECRET",
                                    "MAGIC_NUMBERS"}))

    def _check_gate(self, name, source):
        """Same check through tools/lint_conventions.py, the RATCHET gate.

        MAGIC_NUMBERS is implemented there, not in convention_lint (the hook), which is
        why the exemption has to be asserted against that module: a MAGIC_NUMBERS
        assertion routed through convention_lint.check_file can only ever be vacuous.
        The two linters share this frozenset, so this is where the sharing is proved.
        """
        import lint_conventions

        path = os.path.join(self.tmp.name, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(source)
        return {v.rule for v in lint_conventions.check_file(path)}

    def test_a_magic_number_in_production_code_is_still_reported(self):
        """The exemption is about test DATA, not about the rule being optional."""
        code = "def gate(n):\n    if n > 4096:\n        return 1\n    return 0\n"
        self.assertIn("MAGIC_NUMBERS", self._check_gate("prod.py", code))

    def test_a_magic_number_in_a_test_is_not_reported(self):
        code = "def test_gate(n):\n    if n > 4096:\n        return 1\n    return 0\n"
        self.assertNotIn("MAGIC_NUMBERS", self._check_gate("test_prod.py", code))

    def test_the_gate_and_the_hook_share_one_exemption_list(self):
        """Two linters, one definition — they drifted by thousands of findings once."""
        import lint_conventions

        made_up = [lint_conventions.ConventionViolation("x.py", 1, rule, "msg")
                   for rule in sorted(cl.TEST_EXEMPT_RULES) + ["MODULE_SINGLETON"]]
        kept_in_a_test = lint_conventions._apply_test_exemption("tests/x.py", made_up)
        self.assertEqual({v.rule for v in kept_in_a_test}, {"MODULE_SINGLETON"})
        kept_in_prod = lint_conventions._apply_test_exemption("runner/x.py", made_up)
        self.assertEqual(len(kept_in_prod), len(made_up))

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
