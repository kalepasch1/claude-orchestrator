#!/usr/bin/env python3
"""The Gemini canary must separate "misconfigured" from "provider down".

The module's own docstring says its whole purpose is keeping two failure modes
separable — a dead credential vs a drifted model. There was a third it could not tell
apart from either: a *misconfiguration*. `GEMINI_MODEL=gemini-2.5` (the family name,
without the `-flash`/`-pro` suffix the endpoint actually serves) produces a 404, and at
05:00 a 404 in the log reads like an outage. Someone gets paged for a typo.

`validate_environment()` catches that class offline, before a request is made, and
`main` returns a distinct exit code for it. These tests pin both, plus the fail-soft
reads of the retry knobs — a bare int() there meant GEMINI_MAX_ATTEMPTS=oops stopped the
canary from starting at all, which also reads like an outage.

No test here touches the network.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import gemini_canary_probe as probe  # noqa: E402

GOOD_KEY = "AIzaSy" + "x" * 30


def env(**over):
    base = {"GEMINI_API_KEY": GOOD_KEY}
    base.update(over)
    return base


class ValidateEnvironmentTest(unittest.TestCase):
    def test_a_good_environment_has_no_problems(self):
        self.assertEqual(probe.validate_environment(env()), [])

    def test_the_default_model_is_accepted_when_unset(self):
        self.assertEqual(probe.validate_environment(env(GEMINI_MODEL="")), [])

    def test_a_missing_key_is_reported(self):
        problems = probe.validate_environment({"GEMINI_API_KEY": ""})
        self.assertTrue(any("GEMINI_API_KEY" in p for p in problems))

    def test_a_truncated_key_is_reported(self):
        problems = probe.validate_environment(env(GEMINI_API_KEY="AIza-short"))
        self.assertTrue(any("truncated" in p for p in problems), problems)

    def test_the_family_name_without_a_variant_is_rejected(self):
        """The concrete trap: gemini-2.5 is not a served id, gemini-2.5-flash is."""
        problems = probe.validate_environment(env(GEMINI_MODEL="gemini-2.5"))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("variant suffix", problems[0])
        self.assertIn("gemini-2.5-flash", problems[0],
                      "the message must name the fix, not just the fault")

    def test_served_ids_are_accepted(self):
        for model in ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash",
                      "gemini-2.5-flash-lite", "gemini-1.5-pro-002"):
            self.assertEqual(probe.validate_environment(env(GEMINI_MODEL=model)), [],
                             model)

    def test_obvious_typos_are_rejected(self):
        for model in ("gemini2.5-flash", "gemni-2.5-flash", "gpt-4o", "flash"):
            self.assertTrue(probe.validate_environment(env(GEMINI_MODEL=model)), model)

    def test_a_non_numeric_timeout_is_reported(self):
        problems = probe.validate_environment(env(GEMINI_TIMEOUT="soon"))
        self.assertTrue(any("not an integer" in p for p in problems), problems)

    def test_a_non_positive_timeout_is_reported(self):
        for bad in ("0", "-5"):
            problems = probe.validate_environment(env(GEMINI_TIMEOUT=bad))
            self.assertTrue(any("positive" in p for p in problems), bad)

    def test_a_valid_timeout_passes(self):
        self.assertEqual(probe.validate_environment(env(GEMINI_TIMEOUT="45")), [])

    def test_several_problems_are_all_reported_not_just_the_first(self):
        problems = probe.validate_environment(
            {"GEMINI_API_KEY": "", "GEMINI_MODEL": "gemini-2.5", "GEMINI_TIMEOUT": "x"})
        self.assertEqual(len(problems), 3, problems)

    def test_it_never_raises(self):
        class Hostile:
            def get(self, *args, **kwargs):
                raise RuntimeError("boom")

        self.assertIsInstance(probe.validate_environment(Hostile()), list)
        self.assertTrue(probe.validate_environment(Hostile()))


class MainExitCodeTest(unittest.TestCase):
    def test_a_misconfiguration_exits_with_its_own_code_and_never_calls_out(self):
        with mock.patch.dict(os.environ, env(GEMINI_MODEL="gemini-2.5"), clear=True):
            with mock.patch.object(probe, "probe_gemini") as called:
                code = probe.main([])
        self.assertEqual(code, probe.EXIT_MISCONFIGURED)
        called.assert_not_called()

    def test_the_misconfigured_code_is_distinct_from_the_failure_code(self):
        self.assertNotIn(probe.EXIT_MISCONFIGURED, (0, 1))

    def test_a_good_environment_proceeds_to_the_probe(self):
        with mock.patch.dict(os.environ, env(GEMINI_MODEL="gemini-2.5-flash"), clear=True):
            with mock.patch.object(probe, "probe_gemini", return_value="canary") as called:
                code = probe.main([])
        self.assertEqual(code, 0)
        called.assert_called_once()

    def test_a_missing_key_no_longer_reaches_the_network(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(probe, "probe_gemini") as called:
                code = probe.main([])
        self.assertEqual(code, probe.EXIT_MISCONFIGURED)
        called.assert_not_called()


class RetryKnobTest(unittest.TestCase):
    def test_malformed_knobs_fall_back_instead_of_raising(self):
        for raw in ("oops", "", "  ", "-1", "0"):
            with mock.patch.dict(os.environ, {"GEMINI_MAX_ATTEMPTS": raw}):
                self.assertEqual(probe._env_number("GEMINI_MAX_ATTEMPTS", 3, int, minimum=1), 3,
                                 raw)

    def test_valid_knobs_are_used(self):
        with mock.patch.dict(os.environ, {"GEMINI_MAX_ATTEMPTS": "5"}):
            self.assertEqual(probe._env_number("GEMINI_MAX_ATTEMPTS", 3, int, minimum=1), 5)

    def test_a_poisoned_knob_does_not_stop_the_module_importing(self):
        """A canary that cannot start reads exactly like the outage it detects."""
        environment = dict(os.environ, GEMINI_MAX_ATTEMPTS="oops",
                           GEMINI_BACKOFF_BASE_S="also-oops", PYTHONPATH=REPO_ROOT)
        result = subprocess.run(
            [sys.executable, "-c",
             "import gemini_canary_probe as p; print(p.MAX_ATTEMPTS, p.BACKOFF_BASE_S)"],
            env=environment, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-1000:])
        self.assertIn("3 1.0", result.stdout)


class ExtractTextIsStillFailSoftTest(unittest.TestCase):
    """Unchanged behaviour, asserted so this slice cannot have broken it."""

    def test_a_well_formed_payload_yields_the_text(self):
        payload = {"candidates": [{"content": {"parts": [{"text": "canary"}]}}]}
        self.assertEqual(probe.extract_text(payload), "canary")

    def test_a_shape_change_degrades_to_empty(self):
        for payload in (None, {}, [], {"candidates": None}, {"candidates": [None]},
                        {"candidates": [{"content": {"parts": [{}]}}]}):
            self.assertEqual(probe.extract_text(payload), "")


if __name__ == "__main__":
    unittest.main()
