"""A turn-budget exhaustion must not look like a provider failure.

The SDK path collapsed every terminal condition into `returncode = 1` with an empty
stderr: `ResultMessage.is_error` was read, `ResultMessage.subtype` — which carries
`error_max_turns` — was discarded. Downstream that produced "agent run failed after 3
error-retries" with nothing to act on.

It matters because model_gateway calls claude with `max_turns=1`, so hitting the turn
budget is the single most likely way that call ends. "The budget ran out and the answer is
truncated" and "the provider failed" are fixed in opposite ways — raise max_turns / split
the task, versus retry or fail over — and the two were indistinguishable.

Deterministic: no network, no SDK, no CLI.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import claude_cli  # noqa: E402
import model_gateway  # noqa: E402


class TestNormalizeTerminalReason:
    def test_the_sdk_max_turns_subtype_is_recognised(self):
        assert claude_cli.normalize_terminal_reason("error_max_turns") == "max_turns"

    def test_the_bare_form_is_recognised_too(self):
        assert claude_cli.normalize_terminal_reason("max_turns") == "max_turns"

    def test_matching_is_case_and_space_insensitive(self):
        assert claude_cli.normalize_terminal_reason("  ERROR_MAX_TURNS ") == "max_turns"

    def test_execution_errors_get_their_own_name(self):
        assert claude_cli.normalize_terminal_reason("error_during_execution") == "execution_error"

    def test_an_unknown_subtype_passes_through_rather_than_being_flattened(self):
        """Discarding a name we do not recognise is the bug this change exists to fix."""
        assert claude_cli.normalize_terminal_reason("error_something_new") == "error_something_new"

    @pytest.mark.parametrize("subtype", [None, "", 0])
    def test_no_subtype_is_no_reason(self, subtype):
        assert claude_cli.normalize_terminal_reason(subtype) == ""


class TestTerminalMessage:
    def test_max_turns_says_what_happened_and_what_to_do(self):
        msg = claude_cli.terminal_message("max_turns", num_turns=1, max_turns=1)
        assert "max_turns" in msg
        assert "truncated" in msg
        assert "raise max_turns" in msg

    def test_it_reports_the_turn_counts(self):
        assert "3 of 5" in claude_cli.terminal_message("max_turns", num_turns=3, max_turns=5)

    def test_an_unknown_reason_still_produces_a_line(self):
        assert "error_something_new" in claude_cli.terminal_message("error_something_new")

    def test_no_reason_is_no_message(self):
        assert claude_cli.terminal_message("") == ""
        assert claude_cli.terminal_message(None) == ""


class FakeResult:
    """Stands in for the SDK's ResultMessage."""

    def __init__(self, is_error=True, subtype="error_max_turns", text="partial answer"):
        self.is_error = is_error
        self.subtype = subtype
        self.result = text
        self.total_cost_usd = 0.01
        self.usage = {"input_tokens": 10, "output_tokens": 5}
        self.num_turns = 1


def _claude_result(reason="max_turns", text="partial answer", returncode=1):
    """What claude_cli.run() returns once the reason is preserved."""
    message = claude_cli.terminal_message(reason, num_turns=1, max_turns=1) if reason else ""
    return {"text": text, "cost_usd": 0.01, "input_tokens": 10, "output_tokens": 5,
            "returncode": returncode, "raw": {"terminal_reason": reason},
            "stderr": message, "error": message or None,
            "terminal_reason": reason, "rate_limit_type": None}


class TestGatewayPreservesIt:
    def _call(self, monkeypatch, result):
        import types
        fake = types.SimpleNamespace(run=lambda *_a, **_k: result)
        monkeypatch.setitem(sys.modules, "claude_cli", fake)
        return model_gateway._call_provider("claude", "claude-x", "hi")

    def test_terminal_reason_survives_the_call_chain(self, monkeypatch):
        out = self._call(monkeypatch, _claude_result())
        assert out["terminal_reason"] == "max_turns"

    def test_the_error_field_is_populated_and_readable(self, monkeypatch):
        out = self._call(monkeypatch, _claude_result())
        assert "max_turns" in out["error"]
        assert "raise max_turns" in out["error"]

    def test_the_partial_text_is_still_returned(self, monkeypatch):
        """max_turns truncates; it does not invalidate what was produced."""
        out = self._call(monkeypatch, _claude_result(text="partial answer"))
        assert out["text"] == "partial answer"

    def test_the_test_fails_if_terminal_reason_is_dropped(self, monkeypatch):
        """The acceptance: dropping the field must break this, not pass silently."""
        dropped = _claude_result()
        dropped.pop("terminal_reason")
        dropped["error"] = None
        dropped["stderr"] = ""
        dropped["returncode"] = 0
        out = self._call(monkeypatch, dropped)
        assert "terminal_reason" not in out
        assert "error" not in out

    def test_a_clean_success_carries_no_error_fields(self, monkeypatch):
        out = self._call(monkeypatch, _claude_result(reason="", text="done", returncode=0))
        assert "terminal_reason" not in out
        assert "error" not in out
        assert out["text"] == "done"

    def test_a_nonzero_returncode_without_a_message_still_reports_an_error(self, monkeypatch):
        bare = _claude_result(reason="", text="", returncode=2)
        out = self._call(monkeypatch, bare)
        assert "returncode 2" in out["error"]

    def test_unrelated_response_fields_are_unchanged(self, monkeypatch):
        out = self._call(monkeypatch, _claude_result())
        assert out["provider"] == "claude"
        assert out["model"] == "claude-x"
        assert out["cost_usd"] == 0.01
