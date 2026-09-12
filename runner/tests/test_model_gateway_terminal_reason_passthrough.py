"""model_gateway must not drop provider diagnostics.

A Claude call that ends because it hit ``--max-turns`` comes back with empty text.
Before this test the gateway rebuilt its own envelope from ``text``/``cost_usd`` only,
so ``terminal_reason`` and ``error`` were discarded and "the agent ran out of turns"
became indistinguishable from "the agent had nothing to say" — the runner retried the
same wedged call instead of escalating.

These tests mock the gateway's own input/output directly (a fake ``claude_cli`` module
in ``sys.modules``). They deliberately do NOT exercise claude_cli, so they stay green
independently of how claude_cli detects the condition.
"""
import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

import model_gateway  # noqa: E402


MAX_TURNS_MESSAGE = "Reached maximum number of turns"


def _fake_claude_cli(payload):
    """A stand-in claude_cli module whose run() returns exactly ``payload``."""
    mod = types.ModuleType("claude_cli")
    mod.run = lambda *a, **k: payload
    return mod


class TerminalReasonPassthroughTest(unittest.TestCase):

    def _call(self, payload):
        with patch.dict(sys.modules, {"claude_cli": _fake_claude_cli(payload)}):
            return model_gateway._call_provider("claude", "claude-sonnet-5", "hi")

    def test_terminal_reason_and_error_survive_the_gateway(self):
        res = self._call({
            "text": "", "cost_usd": 0.0,
            "terminal_reason": "max_turns",
            "error": MAX_TURNS_MESSAGE,
            "error_max_turns": True,
        })
        self.assertEqual(res["terminal_reason"], "max_turns")
        self.assertEqual(res["error"], MAX_TURNS_MESSAGE)
        self.assertTrue(res["error_max_turns"])

    def test_normal_envelope_fields_still_present(self):
        res = self._call({
            "text": "", "cost_usd": 0.0, "terminal_reason": "max_turns",
            "error": MAX_TURNS_MESSAGE,
        })
        self.assertEqual(res["provider"], "claude")
        self.assertEqual(res["model"], "claude-sonnet-5")
        self.assertEqual(res["text"], "")
        self.assertEqual(res["cost_usd"], 0.0)

    def test_other_diagnostics_pass_through(self):
        res = self._call({
            "text": "", "cost_usd": 0.0, "returncode": 1,
            "stderr": "usage limit reached", "rate_limit_type": "five_hour",
        })
        self.assertEqual(res["returncode"], 1)
        self.assertEqual(res["stderr"], "usage limit reached")
        self.assertEqual(res["rate_limit_type"], "five_hour")

    def test_clean_success_adds_no_spurious_diagnostic_keys(self):
        res = self._call({"text": "ok", "cost_usd": 0.25})
        self.assertEqual(res["text"], "ok")
        for key in ("error", "terminal_reason", "error_max_turns"):
            self.assertNotIn(key, res)

    def test_carry_diagnostics_is_fail_soft_on_garbage(self):
        base = {"text": "", "cost_usd": 0}
        self.assertEqual(model_gateway._carry_diagnostics(None, dict(base)), base)
        self.assertEqual(model_gateway._carry_diagnostics("nope", dict(base)), base)
        self.assertEqual(model_gateway._carry_diagnostics([1, 2], dict(base)), base)

    def test_carry_diagnostics_never_overwrites_existing_keys(self):
        dst = {"text": "", "error": "original"}
        out = model_gateway._carry_diagnostics({"error": "provider"}, dst)
        self.assertEqual(out["error"], "original")

    def test_none_valued_diagnostics_are_not_copied(self):
        res = self._call({"text": "ok", "cost_usd": 0, "terminal_reason": None})
        self.assertNotIn("terminal_reason", res)

    def test_missing_text_and_cost_default_safely(self):
        res = self._call({"terminal_reason": "max_turns"})
        self.assertEqual(res["text"], "")
        self.assertEqual(res["cost_usd"], 0)
        self.assertEqual(res["terminal_reason"], "max_turns")


if __name__ == "__main__":
    unittest.main()
