"""End-to-end guard: a max_turns run stays a well-formed result, and never raises.

Companion to test_claude_cli_max_turns.py. That module pins DETECTION; this one pins the
CONTRACT callers depend on — every run() result is a dict with a stable key set, reading
it never raises, and `succeeded()`/`failure_reason()` classify a turn-budget stop as the
failure it is instead of letting it pass as a completion.
"""
import json
import os
import sys
import types

import pytest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import claude_cli  # noqa: E402

REQUIRED_KEYS = {"text", "cost_usd", "input_tokens", "output_tokens",
                 "returncode", "raw", "stderr", "terminal_reason", "error"}

MAX_TURNS_STDOUT = json.dumps({
    "type": "result", "subtype": "error_max_turns", "is_error": True,
    "num_turns": 2, "stop_reason": "tool_use", "total_cost_usd": 0.0,
})


@pytest.fixture
def stub_cli(monkeypatch):
    """Run the CLI subprocess path against a canned stdout, with no side effects."""
    def _install(stdout, stderr="", returncode=0):
        monkeypatch.setattr(claude_cli, "_paused", lambda project=None: False)
        monkeypatch.setattr(claude_cli, "_check_budget", lambda: None)
        monkeypatch.setattr(claude_cli, "_record", lambda *a, **k: None)
        monkeypatch.setattr(
            claude_cli.subprocess, "run",
            lambda *a, **k: types.SimpleNamespace(
                stdout=stdout, stderr=stderr, returncode=returncode),
        )
        monkeypatch.setenv("ORCH_USE_SDK", "false")
    return _install


def test_max_turns_result_is_well_formed_and_does_not_raise(stub_cli):
    stub_cli(MAX_TURNS_STDOUT)
    res = claude_cli.run("p", "claude-haiku-4-5-20251001")

    assert isinstance(res, dict)
    assert REQUIRED_KEYS <= set(res), f"missing keys: {REQUIRED_KEYS - set(res)}"
    assert isinstance(res["text"], str)
    assert res["terminal_reason"] == claude_cli.TERMINAL_MAX_TURNS
    # reading every field is safe — no lazy value blows up on access
    assert json.dumps({k: str(v) for k, v in res.items()})


def test_max_turns_is_not_reported_as_success(stub_cli):
    stub_cli(MAX_TURNS_STDOUT)
    res = claude_cli.run("p", "claude-haiku-4-5-20251001")
    assert claude_cli.succeeded(res) is False
    reason = claude_cli.failure_reason(res)
    assert reason and reason.startswith("max_turns:")


def test_normal_run_is_success_with_no_reason(stub_cli):
    stub_cli(json.dumps({"result": "done", "total_cost_usd": 0.0,
                         "usage": {"input_tokens": 1, "output_tokens": 2}}))
    res = claude_cli.run("p", "claude-haiku-4-5-20251001")
    assert claude_cli.succeeded(res) is True
    assert claude_cli.failure_reason(res) is None


def test_non_json_stdout_still_yields_the_full_key_set(stub_cli):
    stub_cli("plain text, older CLI", stderr="", returncode=0)
    res = claude_cli.run("p", "claude-haiku-4-5-20251001")
    assert REQUIRED_KEYS <= set(res)
    assert claude_cli.succeeded(res) is True


def test_legacy_result_without_terminal_reason_reads_as_success():
    """Callers holding an old-shaped dict must not start failing."""
    assert claude_cli.succeeded({"text": "ok", "returncode": 0}) is True
    assert claude_cli.failure_reason({"text": "ok", "returncode": 0}) is None


@pytest.mark.parametrize("bad", [None, "", 0, [], object()])
def test_classifiers_are_fail_soft_on_non_dicts(bad):
    assert claude_cli.succeeded(bad) is False
    assert claude_cli.failure_reason(bad)


def test_failure_reason_is_never_empty_for_a_failure():
    for res in ({"returncode": 1}, {"returncode": 1, "stderr": "   "},
                {"returncode": 0, "terminal_reason": "error"},
                {"returncode": 75, "skipped": "kill_switch"}):
        reason = claude_cli.failure_reason(res)
        assert reason and reason.strip(), f"empty reason for {res}"


def test_paused_run_is_a_reported_failure_not_a_silent_empty(monkeypatch):
    monkeypatch.setattr(claude_cli, "_paused", lambda project=None: True)
    res = claude_cli.run("p", "claude-haiku-4-5-20251001")
    assert claude_cli.succeeded(res) is False
    assert "kill_switch" in claude_cli.failure_reason(res)
