#!/usr/bin/env python3
"""canary.py --probe: the two halves of the canary, finally joined.

`gemini_canary_probe.py` owns the live call. `canary.py` owns the verdict. Both were
finished, tested and shipped — and nothing called one from the other, so no process in
the fleet actually ran the canary end to end. This slice adds `probe_and_validate`,
which is the join, and these tests pin the exit-code contract that makes the join worth
having:

    0  marker present                     — healthy
    1  reply arrived, no marker           — MODEL DRIFT, a human should look
    4  probe raised                       — outage or credential, page differently
    5  probe module not importable        — the canary itself is broken

1 vs 4 is the whole point. "The model answered something else" and "we never reached
the model" need opposite responses, and gemini_canary_probe's own docstring says
keeping them separable is why it exists.

`probe_fn` is injected in every test — no key, no network.
"""
from __future__ import annotations

import importlib.util
import io
import os
import sys
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _load_root_canary():
    """Load the ROOT canary.py by path.

    `runner/canary.py` is a different module with the same name (it renders a
    deployment rollback verdict), and whichever directory pytest puts on sys.path first
    wins a bare `import canary`. Loading by path is the only way to be sure which of the
    two is under test — a plain import silently tested the wrong file.
    """
    path = os.path.join(REPO_ROOT, "canary.py")
    spec = importlib.util.spec_from_file_location("root_canary", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["root_canary"] = module
    spec.loader.exec_module(module)
    return module


canary = _load_root_canary()


class ExitCodeContractTest(unittest.TestCase):
    def test_a_marker_reply_is_healthy(self):
        out = io.StringIO()
        code = canary.probe_and_validate(probe_fn=lambda key: "canary", out=out)
        self.assertEqual(code, 0)
        self.assertIn("canary", out.getvalue())

    def test_a_reply_without_the_marker_is_model_drift_not_an_outage(self):
        code = canary.probe_and_validate(probe_fn=lambda key: "I am a large language model",
                                         out=io.StringIO())
        self.assertEqual(code, 1)

    def test_a_raising_probe_is_an_outage_not_drift(self):
        def boom(key):
            raise RuntimeError("gemini probe exhausted 3 attempts")

        code = canary.probe_and_validate(probe_fn=boom, out=io.StringIO())
        self.assertEqual(code, canary.EXIT_PROBE_FAILED)

    def test_a_rejected_credential_is_also_routed_as_probe_failure(self):
        def boom(key):
            raise ValueError("GEMINI_API_KEY is empty or unset")

        self.assertEqual(canary.probe_and_validate(probe_fn=boom, out=io.StringIO()),
                         canary.EXIT_PROBE_FAILED)

    def test_the_four_outcomes_have_four_different_codes(self):
        codes = {0, 1, canary.EXIT_PROBE_FAILED, canary.EXIT_PROBE_UNAVAILABLE}
        self.assertEqual(len(codes), 4)

    def test_the_probe_codes_do_not_collide_with_the_request_only_codes(self):
        """2 and 3 already mean 'unreadable body' and 'unparseable response'."""
        self.assertNotIn(canary.EXIT_PROBE_FAILED, (0, 1, 2, 3))
        self.assertNotIn(canary.EXIT_PROBE_UNAVAILABLE, (0, 1, 2, 3))

    def test_a_missing_probe_module_is_reported_as_such(self):
        with mock.patch.dict(sys.modules, {"gemini_canary_probe": None}):
            code = canary.probe_and_validate(out=io.StringIO())
        self.assertEqual(code, canary.EXIT_PROBE_UNAVAILABLE)

    def test_a_non_string_reply_does_not_crash_the_verdict(self):
        code = canary.probe_and_validate(probe_fn=lambda key: None, out=io.StringIO())
        self.assertEqual(code, 1, "an unusable reply is drift, not a crash")

    def test_the_reply_is_printed_so_a_human_can_see_what_arrived(self):
        out = io.StringIO()
        canary.probe_and_validate(probe_fn=lambda key: "not the word", out=out)
        self.assertIn("not the word", out.getvalue())

    def test_the_key_is_passed_through_from_the_environment(self):
        seen = []
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "sentinel-key"}):
            canary.probe_and_validate(probe_fn=lambda key: seen.append(key) or "canary",
                                      out=io.StringIO())
        self.assertEqual(seen, ["sentinel-key"])


class CliRoutingTest(unittest.TestCase):
    def test_probe_flag_routes_to_probe_and_validate(self):
        with mock.patch.object(canary, "probe_and_validate", return_value=0) as called:
            self.assertEqual(canary.main(["--probe"]), 0)
        called.assert_called_once()

    def test_the_existing_text_mode_is_unchanged(self):
        self.assertEqual(canary.main(["the canary is fine"]), 0)
        self.assertEqual(canary.main(["nothing here"]), 1)

    def test_the_existing_request_only_mode_is_unchanged(self):
        with mock.patch.object(canary, "request_only", return_value=0) as called:
            self.assertEqual(canary.main(["--request-only", "/tmp/x.json"]), 0)
        called.assert_called_once_with("/tmp/x.json")


class RealProbeSignatureTest(unittest.TestCase):
    """The join only holds if the two modules' signatures actually fit."""

    def test_probe_gemini_accepts_the_key_positionally(self):
        import inspect

        import gemini_canary_probe

        params = list(inspect.signature(gemini_canary_probe.probe_gemini).parameters)
        self.assertEqual(params[0], "api_key",
                         "canary.probe_and_validate calls probe_gemini(key) positionally")

    def test_the_probe_prompt_asks_for_the_word_this_module_validates(self):
        import gemini_canary_probe

        self.assertTrue(canary.validate_canary(gemini_canary_probe.PROMPT),
                        "the probe must ask for the marker canary.py checks for")


if __name__ == "__main__":
    unittest.main()
