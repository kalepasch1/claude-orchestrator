#!/usr/bin/env python3
"""Acceptance test for the ROOT canary.py (canary-gemini-25 validate slice).

Every assertion logs: INFO for the case being exercised, WARNING when the case is a
rejection path, because the acceptance for this slice is explicitly "logs appropriate
info and warning messages for each assertion" — an operator reading a canary run's
output has to be able to see which case failed without a debugger.

WHY THIS FILE EXISTS ALONGSIDE tests/test_validate_canary.py: that file puts runner/ on
sys.path and therefore tests runner/canary.py. The repo has THREE modules named canary*
and the root one — the CLI entry point, the one with parse_gemini_text and the exit-code
contract — had no test of its own. `import canary` cannot distinguish them (sys.modules
caches whichever a sibling test imported first), so this loads the root file by PATH
under a unique module name.
"""
import importlib.util
import io
import logging
import os
import tempfile
import unittest

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("test_canary_acceptance")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CANARY_PATH = os.path.join(_ROOT, "canary.py")
_spec = importlib.util.spec_from_file_location("root_canary_acceptance", _CANARY_PATH)
canary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(canary)


def _gemini(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class ValidateCanaryAcceptance(unittest.TestCase):
    """str -> bool, case-insensitive, word-boundary."""

    ACCEPTED = ["canary", "CANARY", "a canary build", "Canary marker present",
                "my-canary-token"]
    REJECTED = ["", "nothing here", "the canaries flew", "canaryish", "precanary"]

    def test_accepted_forms_return_true(self):
        for text in self.ACCEPTED:
            log.info("expect True: validate_canary(%r)", text)
            self.assertTrue(canary.validate_canary(text), text)

    def test_rejected_forms_return_false(self):
        for text in self.REJECTED:
            log.warning("expect False (rejection path): validate_canary(%r)", text)
            self.assertFalse(canary.validate_canary(text), text)

    def test_the_return_value_is_a_real_bool_not_a_truthy_match_object(self):
        """A caller doing `is True` must not be surprised by an re.Match."""
        log.info("expect bool type from validate_canary")
        self.assertIs(canary.validate_canary("canary"), True)
        self.assertIs(canary.validate_canary("nope"), False)

    def test_non_string_input_is_false_and_warns(self):
        for bad in (None, 42, [], {}, object()):
            log.warning("expect False + WARNING (fail-soft path): %r", type(bad).__name__)
            with self.assertLogs(canary.logger, level="WARNING"):
                self.assertFalse(canary.validate_canary(bad))


class ParseGeminiTextAcceptance(unittest.TestCase):
    """Every malformed shape must surface as GeminiResponseError, never KeyError."""

    MALFORMED = [
        ("not json at all", "unparseable string"),
        ("[]", "top-level list"),
        ('{"candidates": []}', "no candidates"),
        ('{"candidates": [{}]}', "candidate without content"),
        ('{"candidates": [{"content": {}}]}', "content without parts"),
        ('{"candidates": [{"content": {"parts": [{}]}}]}', "part without text"),
        ('{"candidates": [{"content": {"parts": [{"text": 7}]}}]}', "non-string text"),
    ]

    def test_a_well_formed_response_yields_the_model_text(self):
        log.info("expect extracted text from a well-formed generateContent response")
        self.assertEqual(canary.parse_gemini_text(_gemini("hello canary")), "hello canary")

    def test_a_json_string_payload_is_accepted_too(self):
        import json
        log.info("expect the raw JSON string form to parse identically")
        self.assertEqual(canary.parse_gemini_text(json.dumps(_gemini("x"))), "x")

    def test_every_malformed_shape_raises_the_declared_error(self):
        for payload, label in self.MALFORMED:
            log.warning("expect GeminiResponseError (rejection path): %s", label)
            with self.assertRaises(canary.GeminiResponseError, msg=label):
                canary.parse_gemini_text(payload)

    def test_a_safety_block_is_diagnosed_as_a_block_not_as_missing_candidates(self):
        log.warning("expect blockReason to be named in the error, not 'no candidates'")
        with self.assertRaises(canary.GeminiResponseError) as ctx:
            canary.parse_gemini_text('{"promptFeedback": {"blockReason": "SAFETY"}}')
        self.assertIn("SAFETY", str(ctx.exception))


class ExitCodeAcceptance(unittest.TestCase):
    """The contract pipelines actually gate on."""

    def test_marker_present_exits_zero(self):
        log.info("expect exit 0 for text carrying the marker")
        self.assertEqual(canary.main(["a", "canary", "build"]), 0)

    def test_marker_absent_exits_one(self):
        log.warning("expect exit 1 (rejection path) for text without the marker")
        self.assertEqual(canary.main(["nothing", "to", "see"]), 1)

    def test_request_only_prints_the_text_and_exits_zero(self):
        import json
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write(json.dumps(_gemini("model said canary")))
            path = fh.name
        try:
            out = io.StringIO()
            log.info("expect exit 0 and the extracted text on stdout")
            self.assertEqual(canary.request_only(path, out=out), 0)
            self.assertIn("model said canary", out.getvalue())
        finally:
            os.unlink(path)

    def test_request_only_exits_three_on_an_unparseable_response(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{not json")
            path = fh.name
        try:
            log.warning("expect exit 3 (parse-failure path)")
            self.assertEqual(canary.request_only(path, out=io.StringIO()), 3)
        finally:
            os.unlink(path)

    def test_request_only_exits_two_when_the_body_cannot_be_read(self):
        log.warning("expect exit 2 (unreadable-body path)")
        self.assertEqual(
            canary.request_only("/nonexistent/canary-response.json", out=io.StringIO()), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
