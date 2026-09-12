"""Offline guards for the scheduled Gemini canary probe.

No network, no credentials: everything here is payload parsing plus the exit-code contract
the workflow gates on. The point is that "the key died" and "the model drifted" must not
collapse into the same signal at 05:00 — probe failure exits non-zero, an unexpected-but-
live reply exits zero and leaves the verdict to canary.py.
"""

import os
import sys
import unittest
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import gemini_canary_probe as probe  # noqa: E402


class TestExtractText(unittest.TestCase):
    def test_reads_the_first_part(self):
        payload = {"candidates": [{"content": {"parts": [{"text": "canary"}]}}]}
        self.assertEqual(probe.extract_text(payload), "canary")

    def test_joins_multiple_parts(self):
        payload = {"candidates": [{"content": {"parts": [{"text": "a"}, {"text": "canary"}]}}]}
        self.assertEqual(probe.extract_text(payload), "a canary")

    def test_unknown_shape_degrades_to_empty(self):
        # Must NOT raise: an upstream schema change should read as "no marker" (canary.py
        # fails loudly) rather than as an infrastructure traceback.
        for payload in ({}, {"candidates": []}, {"candidates": [{}]}, None, "text", 7,
                        {"candidates": [{"content": {"parts": [{"inlineData": {}}]}}]}):
            with self.subTest(payload=payload):
                self.assertEqual(probe.extract_text(payload), "")


class TestProbeContract(unittest.TestCase):
    def test_missing_key_is_rejected_before_any_request(self):
        with self.assertRaises(ValueError):
            probe.probe_gemini("")

    def test_http_error_exits_nonzero(self):
        # The invalid/expired-key case named in the acceptance criteria.
        def boom(*_args, **_kwargs):
            raise urllib.error.HTTPError("url", 403, "Forbidden", None, None)

        original, probe.probe_gemini = probe.probe_gemini, boom
        try:
            self.assertEqual(probe.main(), 1)
        finally:
            probe.probe_gemini = original

    def test_live_but_unexpected_output_still_exits_zero(self):
        # Deliberate: a reachable model returning junk is canary.py's verdict to make,
        # not the probe's. Conflating them loses the diagnosis.
        original, probe.probe_gemini = probe.probe_gemini, lambda *a, **k: "sparrow"
        try:
            self.assertEqual(probe.main(), 0)
        finally:
            probe.probe_gemini = original

    def test_a_non_numeric_timeout_is_reported_not_silently_swallowed(self):
        """GEMINI_TIMEOUT=not-a-number is a typo, and main() now says so.

        This used to assert exit 0 — main() parsed the timeout, hit ValueError,
        fell back to the default and probed anyway. validate_environment() runs
        first now and refuses, which is the module's stated purpose: "reporting a
        typo'd model id or a truncated key as a PROVIDER failure is the failure
        mode this module exists to prevent". A silently-ignored timeout is the
        same class of thing — the operator who set it never learns it did
        nothing. Asserting 0 here would pin the swallow.
        """
        os.environ["GEMINI_API_KEY"] = "A" * 40
        os.environ["GEMINI_TIMEOUT"] = "not-a-number"
        original, probe.probe_gemini = probe.probe_gemini, lambda *a, **k: "canary"
        try:
            self.assertEqual(probe.main(), probe.EXIT_MISCONFIGURED)
            problems = probe.validate_environment()
            self.assertTrue(any("GEMINI_TIMEOUT" in p for p in problems), problems)
        finally:
            probe.probe_gemini = original
            os.environ.pop("GEMINI_TIMEOUT", None)
            os.environ.pop("GEMINI_API_KEY", None)

    def test_the_timeout_parse_still_falls_back_rather_than_raising(self):
        """The fallback is still there and still correct; it is just no longer reached
        with garbage, because validate_environment refuses that first. Pinned so a
        future caller that bypasses validation does not get a ValueError."""
        os.environ["GEMINI_API_KEY"] = "A" * 40
        os.environ["GEMINI_TIMEOUT"] = "45"
        original, probe.probe_gemini = probe.probe_gemini, lambda *a, **k: "canary"
        try:
            self.assertEqual(probe.main(), 0)
        finally:
            probe.probe_gemini = original
            os.environ.pop("GEMINI_TIMEOUT", None)
            os.environ.pop("GEMINI_API_KEY", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
