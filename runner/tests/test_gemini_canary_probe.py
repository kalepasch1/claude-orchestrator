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

    def test_non_numeric_timeout_falls_back(self):
        os.environ["GEMINI_TIMEOUT"] = "not-a-number"
        original, probe.probe_gemini = probe.probe_gemini, lambda *a, **k: "canary"
        try:
            self.assertEqual(probe.main(), 0)
        finally:
            probe.probe_gemini = original
            os.environ.pop("GEMINI_TIMEOUT", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
