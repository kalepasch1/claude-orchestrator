"""HARDCODED_SECRET must name credentials, not every constant with KEY in it.

tools/lint_conventions.py tested names with a bare ``'key' in var_name``. That matched
every KV-namespace constant in the runner — ``_ALERT_KEY``, ``PRESSURE_KEY``,
``STATE_KEY``, ``DONE_KEY``, ``problem_key`` — producing 144 findings that were almost
entirely noise, 11 above the rule's ratchet baseline of 133. Because the ratchet fails on
ANY rule rising, that noise kept the whole pre-commit gate red, so every other rule went
unenforced too and the working practice became ``--no-verify``.

The name test now lives in tools/secret_names.py and matches whole credential tokens.
These are the assertions for that changed function and for the rule that calls it.
"""

import importlib.util
import os
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(alias, *parts):
    """Load by PATH: `lint_conventions` names two different files in this repo."""
    spec = importlib.util.spec_from_file_location(alias, os.path.join(REPO, *parts))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


secret_names = _load("_sn_secret_names", "tools", "secret_names.py")
lint_conventions = _load("_sn_lint_conventions", "tools", "lint_conventions.py")


#: The exact identifiers the old bare-'key' test misfired on, taken from the scan output.
NOISE_NAMES = (
    "_ALERT_KEY", "ADVISORY_KEY", "LIVE_BUDGET_KEY", "PATTERNS_KEY", "DONE_KEY",
    "_KEY_PREFIX", "IGNORE_UNSAFE_KEY", "PRESSURE_KEY", "key", "CONTROL_KEY",
    "STATE_KEY", "BUDGET_KEY", "problem_key",
)

#: Names that really do hold a credential and must keep firing.
CREDENTIAL_NAMES = (
    "db_password", "PASSWORD", "api_key", "API_KEY", "apiKey", "private_key",
    "access_key", "signing_key", "client_secret", "AUTH_TOKEN", "credential",
)

#: Names that mention a credential but hold where to find it, not the value.
INDIRECTION_NAMES = (
    "TOKEN_ENV", "SECRET_PATH", "API_KEY_NAME", "PASSWORD_FILE", "SECRET_URL",
)


class NamesASecretTest(unittest.TestCase):
    """Direct assertions on the changed function."""

    def test_kv_namespace_constants_are_not_credentials(self):
        """THE REGRESSION: these 13 shapes were the bulk of the 144 findings."""
        for name in NOISE_NAMES:
            with self.subTest(name=name):
                self.assertFalse(secret_names.names_a_secret(name))

    def test_real_credential_names_still_match(self):
        for name in CREDENTIAL_NAMES:
            with self.subTest(name=name):
                self.assertTrue(secret_names.names_a_secret(name))

    def test_indirection_names_are_exempt(self):
        for name in INDIRECTION_NAMES:
            with self.subTest(name=name):
                self.assertFalse(secret_names.names_a_secret(name))

    def test_is_fail_soft_on_junk(self):
        for junk in (None, "", 0, [], {}, object()):
            self.assertIsInstance(secret_names.names_a_secret(junk), bool)


class RuleUsesThePreciseTestTest(unittest.TestCase):
    """The rule as the pre-commit hook invokes it."""

    def _rules(self, code):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as fh:
            fh.write(code)
            fh.flush()
            path = fh.name
        try:
            return [v.rule for v in lint_conventions.check_file(path)]
        finally:
            os.unlink(path)

    def test_namespace_constant_no_longer_reported(self):
        self.assertNotIn("HARDCODED_SECRET", self._rules('PRESSURE_KEY = "fleet:pressure"'))

    def test_real_secret_still_reported(self):
        self.assertIn("HARDCODED_SECRET", self._rules('db_password = "hunter2"'))

    def test_subscript_target_uses_the_same_test(self):
        self.assertNotIn(
            "HARDCODED_SECRET", self._rules('cfg["STATE_KEY"] = "fleet:state"'))
        self.assertIn(
            "HARDCODED_SECRET", self._rules('cfg["DB_PASSWORD"] = "hunter2"'))

    def test_env_indirection_still_clean(self):
        self.assertNotIn("HARDCODED_SECRET", self._rules('api_key = "$API_KEY"'))

    def test_the_linter_binds_the_shared_helper_not_a_private_copy(self):
        # Identity would be the cleaner assertion, but this test loads secret_names
        # under an alias while the linter imports the real module, so they are two
        # function objects from the same file. Compare origin, then behavior.
        bound = lint_conventions._names_a_secret
        self.assertEqual(bound.__module__, "secret_names",
                         "linter fell back to its inline copy instead of tools/secret_names.py")
        for name in NOISE_NAMES + CREDENTIAL_NAMES + INDIRECTION_NAMES:
            with self.subTest(name=name):
                self.assertEqual(bound(name), secret_names.names_a_secret(name))


if __name__ == "__main__":
    unittest.main()
