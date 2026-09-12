"""The smoke runner must START, whatever the environment hands it.

OBSERVED (canary-deepseek-6 "set up and verify the test environment" slice). The
suite's two knobs were read as bare `int(os.environ.get(...))`, one of them at module
scope:

    SMOKE_TEST_TIMEOUT= python3 -c 'import smoke_test_runner'
    ValueError: invalid literal for int() with base 10: ''

An env var exported empty — the usual way a CI matrix or a shell wrapper "unsets" one —
did not degrade the suite, it made the module unimportable, so the runner could not
start and the traceback blamed line 22 instead of the environment. Acceptance for that
slice is precisely "does not produce environment-related errors and the test runner
starts successfully", so it is tested here as a startup property.

`verify_environment()` is the other half: a caller preflights readiness instead of
discovering a misconfiguration a suite-timeout later.
"""
import importlib
import os
import sys
import unittest
from unittest import mock

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import smoke_test_runner as st  # noqa: E402


def _reimport(env):
    with mock.patch.dict(os.environ, env, clear=False):
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
        return importlib.reload(st)


class ImportSurvivesABadEnvironmentTest(unittest.TestCase):
    """A misconfigured knob must never stop the module from loading."""

    def tearDown(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SMOKE_TEST_TIMEOUT", None)
            os.environ.pop("SMOKE_TEST_SUITE_TIMEOUT", None)
            importlib.reload(st)

    def test_empty_request_timeout_does_not_break_import(self):
        m = _reimport({"SMOKE_TEST_TIMEOUT": ""})
        self.assertEqual(m._REQUEST_TIMEOUT, m._DEFAULT_REQUEST_TIMEOUT)

    def test_non_numeric_request_timeout_does_not_break_import(self):
        m = _reimport({"SMOKE_TEST_TIMEOUT": "thirty"})
        self.assertEqual(m._REQUEST_TIMEOUT, m._DEFAULT_REQUEST_TIMEOUT)

    def test_whitespace_is_tolerated(self):
        m = _reimport({"SMOKE_TEST_TIMEOUT": "  45  "})
        self.assertEqual(m._REQUEST_TIMEOUT, 45)

    def test_a_valid_value_is_still_honoured(self):
        m = _reimport({"SMOKE_TEST_TIMEOUT": "7"})
        self.assertEqual(m._REQUEST_TIMEOUT, 7)


class EnvIntTest(unittest.TestCase):
    def test_unset_returns_the_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOPE_X", None)
            self.assertEqual(st._env_int("NOPE_X", 11), 11)

    def test_zero_and_negative_are_rejected(self):
        for bad in ("0", "-5"):
            with self.subTest(bad=bad), mock.patch.dict(os.environ, {"K": bad}):
                self.assertEqual(st._env_int("K", 30), 30)

    def test_floats_are_rejected_rather_than_truncated(self):
        with mock.patch.dict(os.environ, {"K": "2.5"}):
            self.assertEqual(st._env_int("K", 30), 30)

    def test_never_raises(self):
        for bad in ("", "   ", "abc", "1e3", "0x10", "None"):
            with self.subTest(bad=bad), mock.patch.dict(os.environ, {"K": bad}):
                self.assertIsInstance(st._env_int("K", 30), int)


class VerifyEnvironmentTest(unittest.TestCase):
    def test_a_clean_environment_is_ready(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SMOKE_TEST_TIMEOUT", None)
            os.environ.pop("SMOKE_TEST_SUITE_TIMEOUT", None)
            report = st.verify_environment()
        self.assertTrue(report["ready"], report["checks"])

    def test_a_bad_knob_is_reported_not_raised(self):
        with mock.patch.dict(os.environ, {"SMOKE_TEST_TIMEOUT": "banana"}):
            report = st.verify_environment()
        self.assertFalse(report["ready"])
        bad = [c for c in report["checks"] if c["status"] == "fail"]
        self.assertTrue(any("SMOKE_TEST_TIMEOUT" in c["name"] for c in bad))
        self.assertTrue(all("detail" in c for c in bad))

    def test_resolved_timeouts_are_always_usable_positive_ints(self):
        with mock.patch.dict(os.environ, {"SMOKE_TEST_TIMEOUT": "",
                                          "SMOKE_TEST_SUITE_TIMEOUT": "-1"}):
            report = st.verify_environment()
        self.assertGreater(report["request_timeout"], 0)
        self.assertGreater(report["suite_timeout"], 0)

    def test_a_non_http_preview_url_fails_the_check(self):
        self.assertFalse(st.verify_environment("example.com")["ready"])

    def test_an_http_preview_url_passes(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SMOKE_TEST_TIMEOUT", None)
            os.environ.pop("SMOKE_TEST_SUITE_TIMEOUT", None)
            self.assertTrue(st.verify_environment("https://x.vercel.app")["ready"])

    def test_the_suite_is_discoverable(self):
        report = st.verify_environment()
        names = [c["name"] for c in report["checks"]]
        self.assertIn("suite discoverable", names)

    def test_it_makes_no_network_call(self):
        with mock.patch.object(st.urllib.request, "urlopen",
                               side_effect=AssertionError("network touched")):
            st.verify_environment("https://x.vercel.app")

    def test_it_never_raises(self):
        for url in (None, "", 5, object(), "ftp://x"):
            with self.subTest(url=url):
                self.assertIn("ready", st.verify_environment(url))


class SuiteStillRunsTest(unittest.TestCase):
    """The env repair must not change what the suite actually does."""

    def test_missing_preview_url_is_still_a_setup_failure(self):
        r = st.run_smoke_tests("")
        self.assertFalse(r["passed"])
        self.assertEqual(r["tests"][0]["name"], "setup")

    def test_a_bad_suite_timeout_no_longer_stops_the_run(self):
        with mock.patch.dict(os.environ, {"SMOKE_TEST_SUITE_TIMEOUT": ""}):
            r = st.run_smoke_tests("https://x.invalid",
                                   suite=[lambda u: {"name": "noop", "status": "pass"}])
        self.assertTrue(r["passed"])

    def test_registered_run_tolerates_a_bad_suite_timeout(self):
        with mock.patch.dict(os.environ, {"SMOKE_TEST_SUITE_TIMEOUT": "nope"}):
            r = st.run_registered_tests("https://x.invalid")
        self.assertIn("tests", r)


if __name__ == "__main__":
    unittest.main()
