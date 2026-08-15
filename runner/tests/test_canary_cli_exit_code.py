#!/usr/bin/env python3
"""Tests for canary.main() — CLI exit-code adherence and JSON output.

The CLI must exit 0 on a 'promote' verdict and 1 on 'rollback' so shell
callers can gate a deploy on the verdict without parsing stdout.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import canary


def test_promote_exits_zero(monkeypatch, capsys):
    # No metrics endpoint configured -> evaluate() returns 'promote'
    monkeypatch.delenv("METRICS_URL", raising=False)
    assert canary.main([]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "promote"


def test_rollback_exits_one(monkeypatch, capsys):
    monkeypatch.setattr(
        canary, "evaluate",
        lambda url=None: {"verdict": "rollback", "reason": "error_rate=9 breaches max 1"},
    )
    assert canary.main(["http://example.test/metrics"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "rollback"


def test_missing_verdict_treated_as_rollback(monkeypatch, capsys):
    # A malformed result must fail closed (non-zero), never silently promote.
    monkeypatch.setattr(canary, "evaluate", lambda url=None: {})
    assert canary.main([]) == 1


def test_stdout_is_json(monkeypatch, capsys):
    monkeypatch.delenv("METRICS_URL", raising=False)
    canary.main([])
    parsed = json.loads(capsys.readouterr().out)
    assert isinstance(parsed, dict)
    assert "verdict" in parsed and "reason" in parsed


def test_argv_url_is_passed_through(monkeypatch, capsys):
    seen = {}

    def fake_evaluate(url=None):
        seen["url"] = url
        return {"verdict": "promote", "reason": "ok"}

    monkeypatch.setattr(canary, "evaluate", fake_evaluate)
    canary.main(["http://example.test/metrics"])
    capsys.readouterr()
    assert seen["url"] == "http://example.test/metrics"


def test_no_argv_defaults_to_env(monkeypatch, capsys):
    seen = {}

    def fake_evaluate(url=None):
        seen["url"] = url
        return {"verdict": "promote", "reason": "ok"}

    monkeypatch.setattr(canary, "evaluate", fake_evaluate)
    canary.main([])
    capsys.readouterr()
    assert seen["url"] is None
