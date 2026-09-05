"""canary.load_env: .env support for the metric-gated deploy CLI.

Every threshold canary.py reads comes from the environment, but nothing loaded a
.env, so an operator exported METRICS_URL and four CANARY_* knobs by hand and a
forgotten export read as "threshold not configured" rather than as an error.

Two contracts are pinned here:
  1. fail-soft — no dotenv, no file, or a malformed file must all return False,
     never raise. A canary that cannot import cannot report.
  2. import stays side-effect free — only main() may touch os.environ, because
     this module is imported by the test suite and the metrics server too.

Imports `canary` from runner/ exactly like test_canary_gauge.py and
test_validate_canary.py do; the repo root holds a *different* canary.py and
putting the root on sys.path here would shadow this one for the whole session.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

import canary  # noqa: E402


class LoadEnvContractTest(unittest.TestCase):
    def test_dotenv_import_is_guarded(self):
        """load_dotenv is the real callable or None — an ImportError never escapes."""
        self.assertTrue(canary.load_dotenv is None or callable(canary.load_dotenv))

    def test_returns_false_when_dotenv_is_not_installed(self):
        with mock.patch.object(canary, "load_dotenv", None):
            self.assertFalse(canary.load_env())

    def test_is_fail_soft_when_the_file_is_malformed(self):
        def boom(*a, **kw):
            raise RuntimeError("malformed .env")
        with mock.patch.object(canary, "load_dotenv", boom):
            self.assertFalse(canary.load_env())  # swallowed, not raised

    def test_returns_false_when_no_file_was_found(self):
        with mock.patch.object(canary, "load_dotenv", lambda *a, **kw: False):
            self.assertFalse(canary.load_env())

    def test_returns_true_when_a_file_was_loaded(self):
        with mock.patch.object(canary, "load_dotenv", lambda *a, **kw: True):
            self.assertTrue(canary.load_env())

    def test_explicit_path_is_forwarded(self):
        seen = {}

        def spy(path=None, *a, **kw):
            seen["path"] = path
            return True
        with mock.patch.object(canary, "load_dotenv", spy):
            canary.load_env("/tmp/custom.env")
        self.assertEqual(seen["path"], "/tmp/custom.env")

    def test_no_path_calls_dotenv_with_no_arguments(self):
        """Bare load_dotenv() is what performs dotenv's own upward file search."""
        seen = {}

        def spy(*a, **kw):
            seen["args"] = a
            return True
        with mock.patch.object(canary, "load_dotenv", spy):
            canary.load_env()
        self.assertEqual(seen["args"], ())


class ImportPurityTest(unittest.TestCase):
    def test_importing_canary_does_not_load_a_dotenv(self):
        """The load belongs to main(), not to import — see the comment in main()."""
        src = open(canary.__file__, encoding="utf-8").read()
        body = src.split("def main(", 1)[0]
        # A module-scope call is an unindented line that is exactly the call.
        # Matching the bare substring would also hit the module docstring, which
        # names load_env() in prose.
        offenders = [ln for ln in body.splitlines() if ln.rstrip() == "load_env()"]
        self.assertEqual(offenders, [],
                         "load_env() must not run at module scope")

    def test_main_loads_env_before_evaluating(self):
        src = open(canary.__file__, encoding="utf-8").read()
        main_body = src.split("def main(", 1)[1]
        self.assertIn("load_env()", main_body.split("def ", 1)[0])


class RealEnvironmentWinsTest(unittest.TestCase):
    def test_existing_environment_variable_is_not_overridden(self):
        """dotenv's no-override default is load-bearing: exports must still win."""
        with mock.patch.dict(os.environ, {"CANARY_MAX_P95_MS": "180"}, clear=False):
            with mock.patch.object(canary, "load_dotenv", lambda *a, **kw: True):
                canary.load_env()
            self.assertEqual(os.environ["CANARY_MAX_P95_MS"], "180")

    def test_threshold_parsing_is_unchanged(self):
        with mock.patch.dict(os.environ, {"CANARY_MAX_P95_MS": "200"}, clear=False):
            self.assertEqual(canary._f("CANARY_MAX_P95_MS"), 200.0)
        with mock.patch.dict(os.environ, {"CANARY_MAX_P95_MS": ""}, clear=False):
            self.assertIsNone(canary._f("CANARY_MAX_P95_MS"))


if __name__ == "__main__":
    unittest.main()
