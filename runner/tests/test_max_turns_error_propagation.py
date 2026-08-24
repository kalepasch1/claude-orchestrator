"""Regression: a run that ends on --max-turns must say so, end to end.

The Claude Code envelope reports this as ``subtype: "error_max_turns"`` with an EMPTY
``result``. Nothing read that field, so ``claude_cli.run()`` returned a normal-looking
``{"text": "", ...}`` and ``model_gateway._call_provider()`` then rebuilt its envelope
from ``text``/``cost_usd`` alone — discarding whatever diagnosis existed. Downstream,
"the agent ran out of turns" was indistinguishable from "the agent had nothing to say",
so the runner retried the same wedged call instead of escalating.

Both halves are covered here: detection in claude_cli, preservation in model_gateway.
"""
import os
import sys
import types
import unittest
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
for _p in (_REPO, os.path.join(_REPO, "runner")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import model_gateway  # noqa: E402


def _load_real_claude_cli():
    """Load runner/claude_cli.py from disk under a private module name.

    Other test modules in this suite install a MagicMock/stub under the name
    ``claude_cli`` in ``sys.modules``; a plain ``import claude_cli`` here then binds
    the stub and the whole file fails on attribute access, depending purely on
    collection order. Loading by path makes these tests order-independent.
    """
    import importlib.util
    name = "_real_claude_cli_for_max_turns_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_REPO, "runner", "claude_cli.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


claude_cli = _load_real_claude_cli()

MSG = "Reached maximum number of turns"


class FakeProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


class DetectMaxTurnsTest(unittest.TestCase):
    """The pure predicate. Fail-soft on every unexpected shape."""

    def test_detects_cli_subtype(self):
        self.assertTrue(claude_cli.detect_max_turns({"subtype": "error_max_turns"}))

    def test_detects_explicit_flag(self):
        self.assertTrue(claude_cli.detect_max_turns({"error_max_turns": True}))

    def test_detects_terminal_reason(self):
        self.assertTrue(claude_cli.detect_max_turns({"terminal_reason": "max_turns"}))

    def test_detects_message_in_text(self):
        self.assertTrue(claude_cli.detect_max_turns({}, text=MSG))

    def test_detects_message_in_stderr(self):
        self.assertTrue(claude_cli.detect_max_turns(None, stderr="Max turns exceeded"))

    def test_clean_result_is_not_flagged(self):
        self.assertFalse(claude_cli.detect_max_turns({"subtype": "success"}, text="done"))

    def test_fail_soft_on_garbage(self):
        for bad in (None, "", 0, [], object()):
            self.assertFalse(claude_cli.detect_max_turns(bad))


class AnnotateMaxTurnsTest(unittest.TestCase):

    def test_annotates_all_three_fields(self):
        out = claude_cli.annotate_max_turns({"text": ""}, raw={"subtype": "error_max_turns"})
        self.assertTrue(out["error_max_turns"])
        self.assertEqual(out["terminal_reason"], "max_turns")
        self.assertEqual(out["error"], MSG)

    def test_preserves_a_more_specific_existing_error(self):
        out = claude_cli.annotate_max_turns(
            {"text": "", "error": "custom"}, raw={"subtype": "error_max_turns"})
        self.assertEqual(out["error"], "custom")

    def test_clean_result_grows_no_error_fields(self):
        out = claude_cli.annotate_max_turns({"text": "hello"}, raw={"subtype": "success"})
        for key in ("error", "terminal_reason", "error_max_turns"):
            self.assertNotIn(key, out)

    def test_non_dict_passes_through(self):
        self.assertEqual(claude_cli.annotate_max_turns("nope"), "nope")


class ClaudeCliRunRegressionTest(unittest.TestCase):
    """claude_cli.run() must surface the condition from a real CLI envelope."""

    def _run(self, proc):
        with patch.object(claude_cli.subprocess, "run", return_value=proc), \
             patch.object(claude_cli, "_paused", return_value=False), \
             patch.object(claude_cli, "_check_budget", return_value=None), \
             patch.object(claude_cli, "_record", return_value=None), \
             patch.dict(os.environ, {"ORCH_USE_SDK": "false", "ORCH_EXEC_MODE": "cli"}):
            return claude_cli.run("prompt", "claude-sonnet-5")

    def test_max_turns_envelope_is_flagged(self):
        envelope = ('{"result": "", "subtype": "error_max_turns", "is_error": true, '
                    '"total_cost_usd": 0}')
        res = self._run(FakeProc(stdout=envelope, returncode=1))
        self.assertTrue(res["error_max_turns"])
        self.assertEqual(res["terminal_reason"], "max_turns")
        self.assertTrue(res["error"])

    def test_successful_envelope_is_not_flagged(self):
        envelope = '{"result": "all done", "subtype": "success", "total_cost_usd": 0.1}'
        res = self._run(FakeProc(stdout=envelope, returncode=0))
        self.assertEqual(res["text"], "all done")
        self.assertNotIn("error_max_turns", res)
        self.assertNotIn("terminal_reason", res)

    def test_non_json_stderr_message_is_flagged(self):
        res = self._run(FakeProc(stdout="", stderr=MSG, returncode=1))
        self.assertTrue(res["error_max_turns"])


def _fake_claude_cli(payload):
    mod = types.ModuleType("claude_cli")
    mod.run = lambda *a, **k: payload
    return mod


class ModelGatewayRegressionTest(unittest.TestCase):
    """model_gateway._call_provider() must preserve what claude_cli reported."""

    def _call(self, payload):
        with patch.dict(sys.modules, {"claude_cli": _fake_claude_cli(payload)}):
            return model_gateway._call_provider("claude", "claude-sonnet-5", "hi")

    def test_error_max_turns_survives_the_gateway(self):
        res = self._call({"text": "", "cost_usd": 0.0, "error_max_turns": True,
                          "terminal_reason": "max_turns", "error": MSG})
        self.assertTrue(res["error_max_turns"])
        self.assertEqual(res["terminal_reason"], "max_turns")
        self.assertEqual(res["error"], MSG)

    def test_envelope_fields_are_still_correct(self):
        res = self._call({"text": "", "cost_usd": 0.0, "error_max_turns": True})
        self.assertEqual(res["provider"], "claude")
        self.assertEqual(res["model"], "claude-sonnet-5")

    def test_clean_call_gains_no_diagnostic_fields(self):
        res = self._call({"text": "ok", "cost_usd": 0.5})
        self.assertEqual(res["text"], "ok")
        for key in ("error", "terminal_reason", "error_max_turns"):
            self.assertNotIn(key, res)

    def test_missing_keys_do_not_raise(self):
        res = self._call({"terminal_reason": "max_turns"})
        self.assertEqual(res["text"], "")
        self.assertEqual(res["terminal_reason"], "max_turns")


class EndToEndTest(unittest.TestCase):
    """The whole seam: CLI envelope in, terminal_reason out of the gateway."""

    def test_cli_envelope_reaches_the_gateway_caller(self):
        envelope = '{"result": "", "subtype": "error_max_turns", "is_error": true}'
        with patch.object(claude_cli.subprocess, "run",
                          return_value=FakeProc(stdout=envelope, returncode=1)), \
             patch.object(claude_cli, "_paused", return_value=False), \
             patch.object(claude_cli, "_check_budget", return_value=None), \
             patch.object(claude_cli, "_record", return_value=None), \
             patch.dict(sys.modules, {"claude_cli": claude_cli}), \
             patch.dict(os.environ, {"ORCH_USE_SDK": "false", "ORCH_EXEC_MODE": "cli"}):
            res = model_gateway._call_provider("claude", "claude-sonnet-5", "hi")
        self.assertEqual(res["terminal_reason"], "max_turns")
        self.assertTrue(res["error_max_turns"])


if __name__ == "__main__":
    unittest.main()
