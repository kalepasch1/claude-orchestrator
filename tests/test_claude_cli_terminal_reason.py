"""A run that ran out of turns must be distinguishable from one that failed.

The SDK path normalised `raw["terminal_reason"]` and documented the contract as
holding for both transports. The CLI subprocess path never set the key, so a CLI
run that died on max_turns arrived downstream as a bare returncode=1 — the exact
condition the SDK-path comment says the normalisation exists to prevent.

These tests pin the normaliser directly (it is the whole of the behaviour) plus
the CLI-path wiring through a stubbed subprocess, so they fail if either the
helper or its call site is removed.
"""
import json
import sys
import types

import pytest

from runner_modules import load


@pytest.fixture(scope="module")
def claude_cli():
    return load("claude_cli")


# --- the normaliser itself ------------------------------------------------

def test_sdk_spelling_maps_to_max_turns(claude_cli):
    raw = {"is_error": True, "subtype": "error_max_turns"}
    claude_cli._normalise_terminal_reason(raw, is_error=True, subtype="error_max_turns")
    assert raw["terminal_reason"] == "max_turns"


def test_cli_spelling_maps_to_max_turns(claude_cli):
    raw = {"is_error": True, "subtype": "max_turns"}
    claude_cli._normalise_terminal_reason(raw, is_error=True, subtype="max_turns")
    assert raw["terminal_reason"] == "max_turns"


def test_prose_only_result_maps_to_max_turns(claude_cli):
    """Some CLI versions say it only in the result string."""
    text = "Reached maximum number of turns (60)"
    raw = {"result": text, "is_error": True}
    claude_cli._normalise_terminal_reason(raw, is_error=True, subtype=None, text=text)
    assert raw["terminal_reason"] == "max_turns"


def test_other_errors_keep_their_own_reason(claude_cli):
    raw = {"is_error": True, "subtype": "error_during_execution"}
    claude_cli._normalise_terminal_reason(raw, is_error=True, subtype="error_during_execution")
    assert raw["terminal_reason"] == "error_during_execution"


def test_success_gets_no_terminal_reason(claude_cli):
    raw = {"is_error": False, "result": "all done"}
    claude_cli._normalise_terminal_reason(raw, is_error=False, subtype=None, text="all done")
    assert "terminal_reason" not in raw


def test_provider_supplied_reason_is_not_overwritten(claude_cli):
    raw = {"is_error": True, "subtype": "max_turns", "terminal_reason": "provider_said_this"}
    claude_cli._normalise_terminal_reason(raw, is_error=True, subtype="max_turns")
    assert raw["terminal_reason"] == "provider_said_this"


def test_non_dict_raw_is_a_no_op_not_a_crash(claude_cli):
    """Runs on the return path of every model call; must never raise."""
    assert claude_cli._normalise_terminal_reason(None, is_error=True) is None
    assert claude_cli._normalise_terminal_reason("junk", is_error=True) == "junk"


# --- the CLI subprocess path ---------------------------------------------

def _stub_run(monkeypatch, claude_cli, stdout, returncode=1, stderr=""):
    """Replace every side effect between run() and the CLI so the test is pure."""
    completed = types.SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)
    monkeypatch.setattr(claude_cli.subprocess, "run", lambda *a, **k: completed)
    monkeypatch.setattr(claude_cli, "_record", lambda *a, **k: None)
    monkeypatch.setattr(claude_cli, "_paused", lambda *a, **k: False)
    # Block the API-direct and Agent-SDK branches so we exercise the CLI path.
    monkeypatch.setenv("ORCH_USE_AGENT_SDK", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    # usage_meter / subscription_tracker are imported lazily inside run(); stub
    # them out so a missing optional dep cannot mask the assertion.
    for name in ("usage_meter", "subscription_tracker"):
        stub = types.ModuleType(name)
        stub.record = lambda *a, **k: None
        stub.record_call = lambda *a, **k: None
        monkeypatch.setitem(sys.modules, name, stub)
    return completed


def test_cli_path_json_envelope_sets_terminal_reason(monkeypatch, claude_cli):
    payload = json.dumps({
        "result": "Reached maximum number of turns",
        "is_error": True,
        "subtype": "max_turns",
        "total_cost_usd": 0.0,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    })
    _stub_run(monkeypatch, claude_cli, payload)

    out = claude_cli.run("do a thing", "claude-haiku-4-5-20251001", max_turns=1)

    # BOTH halves of the contract: the max_turns detail AND terminal_reason.
    assert out["raw"]["subtype"] == "max_turns"
    assert out["raw"]["terminal_reason"] == "max_turns"
    assert out["returncode"] == 1


def test_cli_path_non_json_output_still_reports_max_turns(monkeypatch, claude_cli):
    """Older CLI emits prose, not JSON — the reason must still survive."""
    _stub_run(monkeypatch, claude_cli, "Error: Reached maximum number of turns\n")

    out = claude_cli.run("do a thing", "claude-haiku-4-5-20251001", max_turns=1)

    assert out["raw"] is not None
    assert out["raw"]["terminal_reason"] == "max_turns"


def test_cli_path_success_has_no_terminal_reason(monkeypatch, claude_cli):
    payload = json.dumps({
        "result": "done",
        "total_cost_usd": 0.0,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    })
    _stub_run(monkeypatch, claude_cli, payload, returncode=0)

    out = claude_cli.run("do a thing", "claude-haiku-4-5-20251001", max_turns=1)

    assert "terminal_reason" not in out["raw"]
