"""Lock in error_max_turns classification so it stops being re-derived by hand.

runner/result_classifier.py is the module that decides whether a provider
response is a real task result or the metadata object the agent returns when it
hits the turn limit. It had NO test coverage at all, which is why its handling
kept getting rebased and re-reasoned: nothing failed when the shape changed.

The contract worth pinning is narrow and easy to widen by accident:
is_error_max_turns() requires BOTH subtype == "error_max_turns" AND
stop_reason == "tool_use". Loosening either half would start classifying
ordinary errors — or ordinary results — as turn-limit metadata, and a
turn-limit classification is what routes a task to the retry/escalate ladder.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import result_classifier as rc


MAX_TURNS = {"subtype": "error_max_turns", "stop_reason": "tool_use"}


class TestIsErrorMaxTurns(unittest.TestCase):
    def test_the_canonical_max_turns_metadata_object_is_detected(self):
        self.assertTrue(rc.is_error_max_turns(MAX_TURNS))

    def test_extra_fields_do_not_prevent_detection(self):
        payload = dict(MAX_TURNS, num_turns=15, total_cost_usd=0.42, result="")
        self.assertTrue(rc.is_error_max_turns(payload))

    def test_both_halves_are_required(self):
        # Each half alone must NOT classify as a turn-limit stop; widening this
        # would misroute ordinary failures into the turn-limit ladder.
        self.assertFalse(rc.is_error_max_turns({"subtype": "error_max_turns"}))
        self.assertFalse(rc.is_error_max_turns({"stop_reason": "tool_use"}))
        self.assertFalse(rc.is_error_max_turns(
            {"subtype": "error_max_turns", "stop_reason": "end_turn"}))
        self.assertFalse(rc.is_error_max_turns(
            {"subtype": "error_during_execution", "stop_reason": "tool_use"}))

    def test_a_normal_result_is_not_max_turns(self):
        self.assertFalse(rc.is_error_max_turns({"result": "done", "is_error": False}))

    def test_non_dict_input_is_fail_soft(self):
        for bad in (None, "", "error_max_turns", [], 0, object()):
            self.assertFalse(rc.is_error_max_turns(bad), repr(bad))


class TestClassify(unittest.TestCase):
    def test_max_turns_is_classified_as_an_error(self):
        verdict = rc.classify(MAX_TURNS)
        self.assertEqual(verdict["type"], "error_max_turns")
        self.assertTrue(verdict["is_error"])

    def test_max_turns_takes_precedence_over_the_generic_error_branch(self):
        # A turn-limit object that also carries is_error must keep its specific
        # type — collapsing it to "error" is exactly how the reason gets lost.
        verdict = rc.classify(dict(MAX_TURNS, is_error=True))
        self.assertEqual(verdict["type"], "error_max_turns")

    def test_a_generic_error_is_classified_as_error(self):
        verdict = rc.classify({"is_error": True, "result": "boom"})
        self.assertEqual(verdict["type"], "error")
        self.assertTrue(verdict["is_error"])

    def test_a_task_result_is_recognised_by_either_key(self):
        for payload in ({"result": "diff"}, {"text": "diff"}):
            verdict = rc.classify(payload)
            self.assertEqual(verdict["type"], "task_result", payload)
            self.assertFalse(verdict["is_error"])

    def test_an_unrecognised_shape_is_unknown_and_not_an_error(self):
        # "unknown" must not be reported as an error: that would send healthy
        # runs into remediation.
        verdict = rc.classify({"cost_usd": 0.1})
        self.assertEqual(verdict["type"], "unknown")
        self.assertFalse(verdict["is_error"])

    def test_non_dict_input_is_fail_soft(self):
        for bad in (None, "text", [], 42):
            verdict = rc.classify(bad)
            self.assertEqual(verdict["type"], "unknown", repr(bad))
            self.assertFalse(verdict["is_error"], repr(bad))

    def test_every_verdict_carries_both_contract_keys(self):
        # Callers index these directly; a missing key would be a KeyError in the
        # failure path, i.e. exactly when it is least welcome.
        for payload in (MAX_TURNS, {"is_error": True}, {"result": "x"}, {}, None):
            verdict = rc.classify(payload)
            self.assertIn("type", verdict)
            self.assertIn("is_error", verdict)
            self.assertIsInstance(verdict["is_error"], bool)


if __name__ == "__main__":
    unittest.main()
