"""The skip reason must actually reach an API response, not just stdout.

These tests exercise the real call sites that decline to run work, and assert
the returned payload carries a classified, actionable reason.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skip_visibility as sv


class CoderCanarySkipPayloadTest(unittest.TestCase):
    def setUp(self):
        sv.clear()

    def tearDown(self):
        sv.clear()

    def test_disabled_flag_returns_visible_reason(self):
        import coder_canary
        with patch.dict(os.environ, {"ORCH_CODER_CANARIES": "0"}, clear=False):
            result = coder_canary.run()
        # Backwards-compatible shape preserved for existing callers.
        self.assertEqual(result["queued"], 0)
        self.assertEqual(result["reason"], "disabled")
        # ...plus the new, actionable visibility.
        self.assertEqual(result["skip"]["category"], sv.CATEGORY_DISABLED)
        self.assertTrue(result["skip"]["remedy"].strip())
        self.assertIn("SKIPPED STEPS", result["skip_summary"])

    def test_skip_payload_is_json_serialisable(self):
        import json
        import coder_canary
        with patch.dict(os.environ, {"ORCH_CODER_CANARIES": "0"}, clear=False):
            result = coder_canary.run()
        json.dumps(result)  # must not raise

    def test_skip_is_recorded_in_the_ledger(self):
        import coder_canary
        with patch.dict(os.environ, {"ORCH_CODER_CANARIES": "0"}, clear=False):
            coder_canary.run()
        self.assertEqual(len(sv.recent(job="coder_canary.py")), 1)

    def test_helper_survives_a_broken_ledger(self):
        import coder_canary
        with patch.object(sv, "record", side_effect=RuntimeError("boom")):
            payload = coder_canary._skipped("disabled")
        self.assertEqual(payload, {"queued": 0, "reason": "disabled"})


class PredictiveSchedulerSkipPayloadTest(unittest.TestCase):
    def setUp(self):
        sv.clear()

    def tearDown(self):
        sv.clear()

    def test_drain_skip_returns_visible_reason(self):
        import predictive_scheduler
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "true"}, clear=False):
            result = predictive_scheduler.run()
        self.assertEqual(result["queued"], 0)
        self.assertIn("drain", result["reason"])
        self.assertEqual(result["skip"]["category"], sv.CATEGORY_DRAIN)
        self.assertIn("ORCH_DRAIN", result["skip"]["remedy"])


class NoteSkipChokepointTest(unittest.TestCase):
    """note_skip is the schedulers' single recording chokepoint (runner._note_skip
    delegates to it); it must record, carry context, and never raise."""

    def setUp(self):
        sv.clear()

    def tearDown(self):
        sv.clear()

    def test_note_skip_records(self):
        sv.note_skip("scout", "drain_mode=auto queue>=800")
        items = sv.recent(job="scout")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].category, sv.CATEGORY_DRAIN)

    def test_note_skip_never_raises_and_returns_none(self):
        with patch.object(sv._ledger, "record", side_effect=RuntimeError("boom")):
            self.assertIsNone(sv.note_skip("scout", "drain_mode=true"))

    def test_note_skip_reports_failure_to_the_logger(self):
        seen = []

        class FakeLog:
            def debug(self, fmt, *args):
                seen.append(fmt % args)

        with patch.object(sv._ledger, "record", side_effect=RuntimeError("boom")):
            sv.note_skip("scout", "drain_mode=true", logger=FakeLog())
        self.assertTrue(any("boom" in line for line in seen))

    def test_note_skip_survives_a_broken_logger(self):
        class ExplodingLog:
            def debug(self, *_a, **_k):
                raise RuntimeError("logger down")

        with patch.object(sv._ledger, "record", side_effect=RuntimeError("boom")):
            self.assertIsNone(sv.note_skip("scout", "x", logger=ExplodingLog()))

    def test_note_skip_carries_context(self):
        sv.note_skip("scout", "throttled - queue depth > 400", context={"ceiling": 400})
        items = sv.recent(job="scout")
        self.assertEqual(items[0].context["ceiling"], "400")
        self.assertEqual(items[0].category, sv.CATEGORY_THROTTLE)

    def test_runner_delegates_to_the_chokepoint(self):
        """Guard against the runner drifting back to its own bespoke recording."""
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "runner.py"), encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn("def _note_skip(", source)
        self.assertIn("skip_visibility.note_skip(", source)


if __name__ == "__main__":
    unittest.main()
