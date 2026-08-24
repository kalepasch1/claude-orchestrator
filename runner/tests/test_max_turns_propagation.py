"""A turn-limit stop must survive as a field, not only as prose in a log tail.

auto_remediate chooses between "retry" and "escalate to a focused prompt" by
matching max_turns in the failure signal. That signal was assembled from note +
log_tail, so when the tail was trimmed the reason disappeared and the run looked
like a generic no-op: the retry ladder restarted from the bottom and the context
was lost. model_gateway._call_provider made it worse by returning only
{text, cost_usd, provider, model}, discarding whatever claude_cli reported.

These pin the propagation end to end and, just as importantly, pin that nothing
else in the response shape changed.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import claude_cli
import model_gateway


class TestDetectTerminalReason(unittest.TestCase):
    def test_explicit_field_spellings_are_all_recognised(self):
        # The SDK has used several names for this across versions.
        for value in ("max_turns", "MAX_TURNS", "max turns", "max-turns"):
            self.assertEqual(claude_cli.detect_terminal_reason(value), "max_turns", value)

    def test_prose_from_the_plain_cli_is_recognised(self):
        self.assertEqual(
            claude_cli.detect_terminal_reason("Error: reached the maximum number of turns"),
            "max_turns")
        self.assertEqual(
            claude_cli.detect_terminal_reason("agent reached its turn limit"), "max_turns")

    def test_an_exhausted_turn_budget_counts_even_when_unlabelled(self):
        # The unlabelled case is exactly how the reason went missing.
        self.assertEqual(
            claude_cli.detect_terminal_reason(None, num_turns=15, max_turns=15), "max_turns")
        self.assertEqual(
            claude_cli.detect_terminal_reason(None, num_turns=20, max_turns=15), "max_turns")

    def test_a_normal_stop_reports_no_reason(self):
        # Must be None, not a falsy string: callers branch on presence.
        self.assertIsNone(claude_cli.detect_terminal_reason(None))
        self.assertIsNone(claude_cli.detect_terminal_reason("", None, ""))
        self.assertIsNone(claude_cli.detect_terminal_reason("all done", num_turns=3, max_turns=15))

    def test_other_terminal_reasons_pass_through(self):
        self.assertEqual(claude_cli.detect_terminal_reason("error_max_tokens"), "error_max_tokens")
        self.assertEqual(claude_cli.detect_terminal_reason("timeout"), "timeout")

    def test_junk_turn_counts_are_fail_soft(self):
        self.assertIsNone(
            claude_cli.detect_terminal_reason(None, num_turns="lots", max_turns="many"))


class TestGatewayPropagation(unittest.TestCase):
    def _call(self, provider_response):
        with patch.dict(sys.modules, {"claude_cli": claude_cli}), \
             patch.object(claude_cli, "run", return_value=provider_response):
            return model_gateway._call_provider("claude", "claude-sonnet-4-6", "hi")

    def test_terminal_reason_and_error_reach_the_caller(self):
        # The acceptance test: mocked provider says max_turns; the result must say so.
        out = self._call({"text": "partial", "cost_usd": 0.01,
                          "terminal_reason": "max_turns",
                          "error": "agent hit the turn limit"})
        self.assertEqual(out["terminal_reason"], "max_turns")
        self.assertEqual(out["error"], "agent hit the turn limit")

    def test_the_original_fields_are_unchanged(self):
        out = self._call({"text": "partial", "cost_usd": 0.01, "terminal_reason": "max_turns"})
        self.assertEqual(out["text"], "partial")
        self.assertEqual(out["cost_usd"], 0.01)
        self.assertEqual(out["provider"], "claude")
        self.assertEqual(out["model"], "claude-sonnet-4-6")

    def test_a_clean_response_gains_no_misleading_keys(self):
        # Backward compatibility: absent is absent, never a None that reads as a value.
        out = self._call({"text": "ok", "cost_usd": 0.02})
        self.assertNotIn("terminal_reason", out)
        self.assertNotIn("error", out)

    def test_returncode_and_rate_limit_type_also_survive(self):
        out = self._call({"text": "", "cost_usd": 0.0, "returncode": 1,
                          "rate_limit_type": "five_hour"})
        self.assertEqual(out["returncode"], 1)
        self.assertEqual(out["rate_limit_type"], "five_hour")

    def test_a_non_dict_provider_response_is_fail_soft(self):
        base = {"text": "t", "cost_usd": 0}
        self.assertEqual(model_gateway._with_failure_fields(dict(base), None), base)
        self.assertEqual(model_gateway._with_failure_fields(dict(base), "junk"), base)


class TestAutoRemediateStillMatches(unittest.TestCase):
    def test_the_propagated_reason_matches_the_remediation_pattern(self):
        # End of the chain: the whole point is that auto_remediate can see it.
        import auto_remediate
        self.assertTrue(auto_remediate._MAX_TURNS.search("max_turns"))


if __name__ == "__main__":
    unittest.main()
