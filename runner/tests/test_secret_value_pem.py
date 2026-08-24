"""HARDCODED_SECRET must fire on a PEM private key.

The value gate in tools/convention_lint.py rejected any literal containing whitespace,
on the reasoning that credentials do not contain spaces and prose does. A PEM block
opens with ``-----BEGIN PRIVATE KEY-----`` — spaces and all — so the most unambiguous
secret literal there is passed the pre-commit linter clean, while ``db_password =
"hunter2"`` was caught. Format-identified credentials now short-circuit the heuristics.

These assertions pin the fix and, just as importantly, pin the suppression behavior it
must not have cost: placeholders, env indirection and prose still do not fire.
"""

import importlib.util
import os
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Imported by PATH: `convention_lint` and `lint_conventions` both name more than one
# file in this repo, and a plain import resolves to whichever directory reached
# sys.path first.
_spec = importlib.util.spec_from_file_location(
    "_pem_convention_lint", os.path.join(REPO, "tools", "convention_lint.py"))
convention_lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(convention_lint)


class SecretValueGateTest(unittest.TestCase):
    """Direct assertions on the changed function, _looks_like_secret_value."""

    def test_pem_private_key_is_a_secret_value(self):
        """THE REGRESSION: whitespace in the PEM header used to disqualify it."""
        self.assertTrue(convention_lint._looks_like_secret_value(
            "-----BEGIN PRIVATE KEY-----..."))

    def test_every_pem_flavor_is_recognised(self):
        for header in ("-----BEGIN RSA PRIVATE KEY-----",
                       "-----BEGIN OPENSSH PRIVATE KEY-----",
                       "-----BEGIN EC PRIVATE KEY-----",
                       "-----BEGIN CERTIFICATE-----"):
            with self.subTest(header=header):
                self.assertTrue(convention_lint._looks_like_secret_value(header))

    def test_vendor_prefixed_literals_are_recognised(self):
        for literal in ("sk-abc123", "ghp_abcdef", "xoxb-1-2-3", "AKIAIOSFODNN7EXAMPLE"):
            with self.subTest(literal=literal):
                self.assertTrue(convention_lint._looks_like_secret_value(literal))

    def test_prose_is_still_not_a_secret(self):
        for prose in ("please set this in the environment",
                      "Hardcoded secret detected in assignment",
                      ""):
            with self.subTest(prose=prose):
                self.assertFalse(convention_lint._looks_like_secret_value(prose))

    def test_env_indirection_is_still_not_a_secret(self):
        for placeholder in ("$SECRET", "${API_TOKEN}"):
            with self.subTest(placeholder=placeholder):
                self.assertFalse(convention_lint._looks_like_secret_value(placeholder))

    def test_gate_is_fail_soft_on_junk(self):
        for junk in (None, 0, [], {}):
            self.assertIsInstance(convention_lint._looks_like_secret_value(junk), bool)


class EndToEndLintTest(unittest.TestCase):
    """The rule as the pre-commit hook actually invokes it."""

    def _rules(self, code):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as fh:
            fh.write(code)
            fh.flush()
            path = fh.name
        try:
            return [v.rule for v in convention_lint.check_file(path)]
        finally:
            os.unlink(path)

    def test_hardcoded_private_key_is_reported(self):
        self.assertIn("HARDCODED_SECRET",
                      self._rules('private_key = "-----BEGIN PRIVATE KEY-----..."'))

    def test_previously_caught_cases_still_fire(self):
        self.assertIn("HARDCODED_SECRET", self._rules('db_password = "hunter2"'))
        self.assertIn("HARDCODED_SECRET", self._rules('API_TOKEN = "ghp_abc123"'))

    def test_env_indirection_still_clean(self):
        self.assertNotIn("HARDCODED_SECRET", self._rules('api_token = "${API_TOKEN}"'))

    def test_empty_placeholder_still_clean(self):
        self.assertNotIn("HARDCODED_SECRET", self._rules('password = ""'))


if __name__ == "__main__":
    unittest.main()
