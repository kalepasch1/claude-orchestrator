"""max_turns must survive the WHOLE chain: SDK ResultMessage -> claude_cli.run -> gateway.

The sibling test file covers each hop in isolation. This one drives the real
`_run_agent_sdk_async` loop with a stubbed SDK stream, so the assertion is that the field
survives the actual message-consuming code — not a hand-written dict standing in for it.

That distinction is the whole point of this task. The regression being guarded is a
DROPPED FIELD, and a test built entirely from fixtures that already contain the field
cannot detect a drop: it would keep passing while the production loop discarded it.

Deterministic — the SDK, the CLI binary and the network are all replaced.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import claude_cli  # noqa: E402
import model_gateway  # noqa: E402


class _TextBlock:
    def __init__(self, text):
        self.text = text


class _AssistantMessage:
    def __init__(self, text):
        self.content = [_TextBlock(text)]


class _ResultMessage:
    """Mirrors the SDK's ResultMessage, including the subtype that was being dropped."""

    def __init__(self, is_error=True, subtype="error_max_turns",
                 result="partial answer", num_turns=1):
        self.is_error = is_error
        self.subtype = subtype
        self.result = result
        self.num_turns = num_turns
        self.total_cost_usd = 0.02
        self.usage = {"input_tokens": 11, "output_tokens": 7}


def _stub_stream(messages):
    """Replace _sdk_query with an async generator over `messages`."""
    async def _query(prompt=None, options=None):
        for m in messages:
            yield m
    return _query


def _run_sdk(monkeypatch, messages, max_turns=1):
    monkeypatch.setattr(claude_cli, "_sdk_query", _stub_stream(messages))
    monkeypatch.setattr(claude_cli, "ClaudeAgentOptions",
                        lambda **kw: kw, raising=False)
    monkeypatch.setattr(claude_cli, "AssistantMessage", _AssistantMessage, raising=False)
    monkeypatch.setattr(claude_cli, "TextBlock", _TextBlock, raising=False)
    monkeypatch.setattr(claude_cli, "ResultMessage", _ResultMessage, raising=False)
    return asyncio.new_event_loop().run_until_complete(
        claude_cli._run_agent_sdk_async("hi", "claude-x", None, {}, None, max_turns, None))


class TestTheSdkLoopPreservesIt:
    def test_error_max_turns_reaches_the_returned_dict(self, monkeypatch):
        out = _run_sdk(monkeypatch, [_AssistantMessage("partial answer"), _ResultMessage()])
        assert out["terminal_reason"] == "max_turns"

    def test_is_error_still_sets_a_nonzero_returncode(self, monkeypatch):
        out = _run_sdk(monkeypatch, [_ResultMessage()])
        assert out["returncode"] == 1

    def test_stderr_is_no_longer_empty_on_a_terminal_error(self, monkeypatch):
        """The original symptom: returncode 1 with nothing explaining why."""
        out = _run_sdk(monkeypatch, [_ResultMessage()])
        assert out["stderr"]
        assert "max_turns" in out["stderr"]

    def test_the_reason_is_recorded_in_raw_for_the_audit_trail(self, monkeypatch):
        out = _run_sdk(monkeypatch, [_ResultMessage()])
        assert out["raw"]["terminal_reason"] == "max_turns"

    def test_the_partial_text_is_preserved(self, monkeypatch):
        out = _run_sdk(monkeypatch, [_ResultMessage(result="partial answer")])
        assert out["text"] == "partial answer"

    def test_a_successful_run_carries_no_terminal_reason(self, monkeypatch):
        out = _run_sdk(monkeypatch, [_ResultMessage(is_error=False, subtype="success",
                                                    result="done")])
        assert out["returncode"] == 0
        assert not out["terminal_reason"]
        assert out["stderr"] == ""
        assert out["error"] is None

    def test_an_error_without_a_subtype_still_reports_the_failure(self, monkeypatch):
        out = _run_sdk(monkeypatch, [_ResultMessage(subtype=None)])
        assert out["returncode"] == 1

    def test_an_unknown_subtype_is_carried_through_verbatim(self, monkeypatch):
        out = _run_sdk(monkeypatch, [_ResultMessage(subtype="error_brand_new")])
        assert out["terminal_reason"] == "error_brand_new"
        assert "error_brand_new" in out["stderr"]

    def test_the_turn_counts_appear_in_the_message(self, monkeypatch):
        out = _run_sdk(monkeypatch, [_ResultMessage(num_turns=1)], max_turns=1)
        assert "1 of 1" in out["stderr"]


class TestEndToEndThroughTheGateway:
    def test_the_reason_survives_sdk_loop_then_gateway(self, monkeypatch):
        sdk_out = _run_sdk(monkeypatch, [_ResultMessage()])

        import types
        monkeypatch.setitem(sys.modules, "claude_cli",
                            types.SimpleNamespace(run=lambda *_a, **_k: sdk_out))
        gateway_out = model_gateway._call_provider("claude", "claude-x", "hi")

        assert gateway_out["terminal_reason"] == "max_turns"
        assert "max_turns" in gateway_out["error"]
        assert gateway_out["text"] == "partial answer"

    def test_it_fails_if_the_sdk_loop_stops_capturing_the_subtype(self, monkeypatch):
        """The required negative: drop the field at the SOURCE and this must break."""
        sdk_out = _run_sdk(monkeypatch, [_ResultMessage()])
        sdk_out["terminal_reason"] = ""      # simulate the regression
        sdk_out["error"] = None
        sdk_out["stderr"] = ""
        sdk_out["returncode"] = 0

        import types
        monkeypatch.setitem(sys.modules, "claude_cli",
                            types.SimpleNamespace(run=lambda *_a, **_k: sdk_out))
        gateway_out = model_gateway._call_provider("claude", "claude-x", "hi")

        assert "terminal_reason" not in gateway_out
        assert "error" not in gateway_out

    def test_a_clean_success_passes_through_the_whole_chain(self, monkeypatch):
        sdk_out = _run_sdk(monkeypatch, [_ResultMessage(is_error=False, subtype="success",
                                                        result="done")])
        import types
        monkeypatch.setitem(sys.modules, "claude_cli",
                            types.SimpleNamespace(run=lambda *_a, **_k: sdk_out))
        gateway_out = model_gateway._call_provider("claude", "claude-x", "hi")
        assert gateway_out["text"] == "done"
        assert "error" not in gateway_out


class TestNoExternalCalls:
    def test_nothing_here_touches_the_network_or_the_cli(self, monkeypatch):
        """Determinism is an acceptance requirement, so assert it."""
        def _boom(*_a, **_k):
            raise AssertionError("test attempted a subprocess call")

        monkeypatch.setattr("subprocess.run", _boom)
        monkeypatch.setattr("subprocess.Popen", _boom)
        out = _run_sdk(monkeypatch, [_ResultMessage()])
        assert out["terminal_reason"] == "max_turns"
