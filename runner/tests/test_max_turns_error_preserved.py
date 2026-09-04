#!/usr/bin/env python3
"""A max_turns termination must survive the trip back to the caller.

THE DEFECT
----------
`claude_cli` has two transports and they disagreed about what a failure carries.

  * CLI path: `raw = json.loads(proc.stdout)` — returned verbatim, so whatever the
    provider reported (is_error, terminal_reason) reached the caller.
  * Agent-SDK path: `raw` was rebuilt from a handful of fields —
    {result, total_cost_usd, usage, agent_sdk, turns} — and `message.is_error` was used
    only to set `returncode = 1` before being thrown away.

So an SDK run that died on max_turns arrived downstream as a bare returncode=1,
indistinguishable from any other failure. Nothing could tell "ran out of turns, give it
more" from "genuinely failed, do not retry" — which is the whole reason the field
exists.

WHY THIS WENT UNNOTICED
-----------------------
test_safety.py has four tests whose docstrings say "claude_cli.run() must detect
terminal_reason='max_turns'". They never call claude_cli. They build a dict literal and
assert that the literal contains what was just written into it:

    mock_response = {"terminal_reason": "max_turns", "is_error": True, ...}
    self.assertEqual(mock_response["terminal_reason"], "max_turns")

That passes whatever claude_cli does, including deleting the field entirely. The tests
below drive the real function with a faked SDK message stream instead.
"""
import asyncio
import importlib.util
import os
import sys
import types

import pytest

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RUNNER)


def _load_private_claude_cli():
    """Load claude_cli from disk under a private name, bypassing sys.modules.

    Other test modules in this suite patch the shared `claude_cli` module and leave
    state behind — running this file alongside them produced StopIteration from a
    stale mock rather than any real failure, while the file passed in isolation. A
    private module instance makes these tests order-independent without reaching into
    another module's cleanup.
    """
    path = os.path.join(_RUNNER, "claude_cli.py")
    if not os.path.isfile(path):  # pragma: no cover
        pytest.skip("claude_cli.py not found")
    spec = importlib.util.spec_from_file_location("_private_claude_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def claude_cli():
    return _load_private_claude_cli()


class FakeResultMessage:
    """Stands in for the SDK's ResultMessage."""

    def __init__(self, *, is_error=False, subtype=None, result="done",
                 num_turns=3, cost=0.01):
        self.is_error = is_error
        self.subtype = subtype
        self.result = result
        self.num_turns = num_turns
        self.total_cost_usd = cost
        self.usage = {"input_tokens": 11, "output_tokens": 22}


def drive(claude_cli, message, monkeypatch):
    """Run _run_agent_sdk_async with a one-message stream and return its result dict."""
    monkeypatch.setattr(claude_cli, "ResultMessage", FakeResultMessage, raising=False)
    monkeypatch.setattr(claude_cli, "AssistantMessage", type("A", (), {}), raising=False)
    monkeypatch.setattr(claude_cli, "TextBlock", type("T", (), {}), raising=False)
    monkeypatch.setattr(claude_cli, "ClaudeAgentOptions",
                        lambda **kw: types.SimpleNamespace(**kw), raising=False)

    async def fake_query(**kwargs):
        yield message

    monkeypatch.setattr(claude_cli, "_sdk_query", fake_query, raising=False)

    coro = claude_cli._run_agent_sdk_async(
        "prompt", "claude-sonnet-5", None, {}, None, 5, 30)
    return asyncio.run(coro)


# ── the regression ──────────────────────────────────────────────────────────

def test_a_max_turns_failure_reports_terminal_reason(claude_cli, monkeypatch):
    """The field this task exists for, read off the REAL return value."""
    result = drive(claude_cli, FakeResultMessage(is_error=True, subtype="error_max_turns"),
                   monkeypatch)
    assert result["raw"]["terminal_reason"] == "max_turns"


def test_a_max_turns_failure_preserves_is_error(claude_cli, monkeypatch):
    result = drive(claude_cli, FakeResultMessage(is_error=True, subtype="error_max_turns"),
                   monkeypatch)
    assert result["raw"]["is_error"] is True


def test_a_max_turns_failure_still_sets_a_nonzero_returncode(claude_cli, monkeypatch):
    """Existing behaviour must not regress while the reason is added."""
    result = drive(claude_cli, FakeResultMessage(is_error=True, subtype="error_max_turns"),
                   monkeypatch)
    assert result["returncode"] == 1


def test_the_raw_subtype_is_preserved_verbatim(claude_cli, monkeypatch):
    """Normalising must not destroy what the provider actually said."""
    result = drive(claude_cli, FakeResultMessage(is_error=True, subtype="error_max_turns"),
                   monkeypatch)
    assert result["raw"]["subtype"] == "error_max_turns"


def test_a_max_turns_failure_is_distinguishable_from_a_generic_one(claude_cli, monkeypatch):
    """The point of the field: two failures that used to look identical."""
    maxed = drive(claude_cli, FakeResultMessage(is_error=True, subtype="error_max_turns"),
                  monkeypatch)
    other = drive(claude_cli, FakeResultMessage(is_error=True, subtype="error_during_execution"),
                  monkeypatch)
    assert maxed["returncode"] == other["returncode"] == 1
    assert maxed["raw"]["terminal_reason"] != other["raw"].get("terminal_reason")


# ── other outcomes are unaffected ───────────────────────────────────────────

def test_a_successful_run_is_not_marked_errored(claude_cli, monkeypatch):
    result = drive(claude_cli, FakeResultMessage(is_error=False, subtype="success"), monkeypatch)
    assert result["returncode"] == 0
    assert result["raw"]["is_error"] is False


def test_a_successful_run_carries_no_terminal_reason(claude_cli, monkeypatch):
    """'Succeeded' must not acquire a failure reason."""
    result = drive(claude_cli, FakeResultMessage(is_error=False, subtype="success"), monkeypatch)
    assert "terminal_reason" not in result["raw"]


def test_a_result_with_no_subtype_still_returns(claude_cli, monkeypatch):
    """Older SDK builds may not expose subtype at all — fail-soft, not KeyError."""
    message = FakeResultMessage(is_error=True)
    del message.subtype
    result = drive(claude_cli, message, monkeypatch)
    assert result["returncode"] == 1
    assert result["raw"]["is_error"] is True


def test_the_existing_raw_fields_are_untouched(claude_cli, monkeypatch):
    """Additive change: nothing downstream loses a field it already read."""
    result = drive(claude_cli, FakeResultMessage(is_error=False, subtype="success"), monkeypatch)
    raw = result["raw"]
    for field in ("result", "total_cost_usd", "usage", "agent_sdk", "turns"):
        assert field in raw, field
    assert raw["turns"] == 3
    assert raw["usage"] == {"input_tokens": 11, "output_tokens": 22}


def test_cost_and_token_accounting_still_flows(claude_cli, monkeypatch):
    result = drive(claude_cli, FakeResultMessage(is_error=False, subtype="success"), monkeypatch)
    assert result["cost_usd"] == 0.01
    assert (result["input_tokens"], result["output_tokens"]) == (11, 22)


# ── the two transports agree ────────────────────────────────────────────────

def test_both_transports_answer_to_the_same_key(claude_cli, monkeypatch):
    """The CLI path returns provider JSON verbatim, which spells it terminal_reason.

    A caller must not have to know which transport produced the result, so the SDK
    path normalises the SDK's own 'error_max_turns' onto the same key.
    """
    sdk = drive(claude_cli, FakeResultMessage(is_error=True, subtype="error_max_turns"), monkeypatch)
    cli_shaped = {"result": "", "is_error": True, "terminal_reason": "max_turns"}
    assert sdk["raw"]["terminal_reason"] == cli_shaped["terminal_reason"]


# ── the tests this file replaces ────────────────────────────────────────────

def test_the_old_style_assertion_would_have_passed_regardless():
    """Documents why the gap survived: the prior tests could not fail.

    test_safety.py builds a dict literal and asserts on that same literal, never
    invoking claude_cli. Reproduced here to make the difference explicit — this passes
    with claude_cli entirely absent, which is exactly the problem.
    """
    mock_response = {"terminal_reason": "max_turns", "is_error": True}
    assert mock_response["terminal_reason"] == "max_turns"
    assert mock_response["is_error"] is True
