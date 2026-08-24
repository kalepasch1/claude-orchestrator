"""claude_cli must report max_turns terminal_reason, not a silent pseudo-success.

Regression: the CLI emits
  {"type":"result","subtype":"error_max_turns","is_error":true,...}
with no "result" key. run() previously fell through to the raw-stdout fallback and
returned a payload indistinguishable from a completed run, so approval-digest batching
kept retrying agents that had merely run out of turns.
"""
import json
import os
import subprocess
import sys
import types

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import claude_cli  # noqa: E402

MAX_TURNS_ENVELOPE = {
    "type": "result",
    "subtype": "error_max_turns",
    "duration_ms": 7157,
    "is_error": True,
    "num_turns": 2,
    "stop_reason": "tool_use",
    "total_cost_usd": 0.0,
}


def test_detect_from_subtype():
    reason, detail = claude_cli.detect_terminal_reason(MAX_TURNS_ENVELOPE, "", "")
    assert reason == claude_cli.TERMINAL_MAX_TURNS
    assert detail and "turn" in detail.lower()
    assert "2" in detail


def test_detect_from_stop_reason():
    reason, detail = claude_cli.detect_terminal_reason(
        {"stop_reason": "max_turns", "is_error": True}, "", ""
    )
    assert reason == claude_cli.TERMINAL_MAX_TURNS
    assert detail


def test_detect_from_free_text():
    reason, _ = claude_cli.detect_terminal_reason(
        None, "Reached maximum number of turns", ""
    )
    assert reason == claude_cli.TERMINAL_MAX_TURNS


def test_normal_completion_has_no_terminal_reason():
    reason, detail = claude_cli.detect_terminal_reason(
        {"result": "all done", "total_cost_usd": 0.01}, "all done", ""
    )
    assert reason is None and detail is None


def test_generic_error_is_not_misreported_as_max_turns():
    reason, detail = claude_cli.detect_terminal_reason(
        {"is_error": True, "error": "boom"}, "", ""
    )
    assert reason == "error"
    assert detail == "boom"


def test_detect_is_fail_soft_on_garbage():
    assert claude_cli.detect_terminal_reason(object(), None, None) == (None, None)


def test_run_surfaces_max_turns_error_and_terminal_reason(monkeypatch):
    """End-to-end through run(): BOTH the error detail and terminal_reason are returned."""
    stdout = json.dumps(MAX_TURNS_ENVELOPE)

    monkeypatch.setattr(claude_cli, "_paused", lambda project=None: False)
    monkeypatch.setattr(claude_cli, "_check_budget", lambda: None)
    monkeypatch.setattr(claude_cli, "_record", lambda *a, **k: None)
    monkeypatch.setattr(
        claude_cli.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(stdout=stdout, stderr="", returncode=0),
    )
    monkeypatch.setenv("ORCH_USE_SDK", "false")

    res = claude_cli.run("do a thing", "claude-haiku-4-5-20251001")

    assert res["terminal_reason"] == claude_cli.TERMINAL_MAX_TURNS
    assert res["error"] and "turn" in res["error"].lower()
    assert res["returncode"] != 0, "max_turns must not look like a successful run"


def test_run_normal_result_reports_no_terminal_reason(monkeypatch):
    stdout = json.dumps({"result": "done", "total_cost_usd": 0.0,
                         "usage": {"input_tokens": 1, "output_tokens": 2}})
    monkeypatch.setattr(claude_cli, "_paused", lambda project=None: False)
    monkeypatch.setattr(claude_cli, "_check_budget", lambda: None)
    monkeypatch.setattr(claude_cli, "_record", lambda *a, **k: None)
    monkeypatch.setattr(
        claude_cli.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(stdout=stdout, stderr="", returncode=0),
    )
    monkeypatch.setenv("ORCH_USE_SDK", "false")

    res = claude_cli.run("do a thing", "claude-haiku-4-5-20251001")
    assert res["terminal_reason"] is None
    assert res["error"] is None
    assert res["returncode"] == 0
    assert res["text"] == "done"
