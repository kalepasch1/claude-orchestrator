"""The self-deploy canary must be passable, and must still block regressions.

Guards the 2026-08-02 finding: canary_gate ran `pytest runner/tests -q -x` with a 300s
cap. `-x` stops at the first failure and the suite has carried pre-existing failures for
months, while a full run takes longer than 300s — so the gate returned False on every
invocation. Self-deploy was structurally impossible and merged code could never reach the
running fleet. An impossible gate is not a safety property, it is a silent outage.
"""
import os
import sys
import tempfile
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import self_deploy as sd


class _FakeRun:
    def __init__(self, rc, out):
        self.returncode, self.stdout, self.stderr = rc, out, ""


def _patched(monkey_out, monkey_rc):
    def _run(*a, **k):
        return _FakeRun(monkey_rc, monkey_out)
    return _run


def test_gate_no_longer_uses_dash_x():
    """`-x` made the gate stop at failure #1, which is why it never went green."""
    src = open(sd.__file__, encoding="utf-8").read()
    cmd_line = [l for l in src.splitlines() if '"pytest", "runner/tests"' in l][0]
    assert '"-x"' not in cmd_line, "canary is back to fail-fast; it can never pass again"


def test_timeout_is_configurable_and_realistic():
    assert sd.CANARY_TIMEOUT >= 600, "a full suite run does not fit in the old 300s cap"


def test_first_run_seeds_a_baseline_and_passes(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr(subprocess, "run", _patched("12 failed, 900 passed", 1))
        assert sd.canary_gate(d) is True
        assert sd._read_baseline(d) == 12


def test_same_failure_count_passes(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        sd._write_baseline(d, 12)
        monkeypatch.setattr(subprocess, "run", _patched("12 failed, 900 passed", 1))
        assert sd.canary_gate(d) is True


def test_regression_blocks_the_deploy(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        sd._write_baseline(d, 12)
        monkeypatch.setattr(subprocess, "run", _patched("13 failed, 899 passed", 1))
        assert sd.canary_gate(d) is False
        assert sd._read_baseline(d) == 12, "a regression must not move the baseline"


def test_improvement_ratchets_the_baseline_down(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        sd._write_baseline(d, 12)
        monkeypatch.setattr(subprocess, "run", _patched("4 failed, 908 passed", 1))
        assert sd.canary_gate(d) is True
        assert sd._read_baseline(d) == 4


def test_fully_green_resets_baseline_to_zero(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        sd._write_baseline(d, 12)
        monkeypatch.setattr(subprocess, "run", _patched("912 passed", 0))
        assert sd.canary_gate(d) is True
        assert sd._read_baseline(d) == 0


def test_crash_without_a_summary_fails_closed(monkeypatch):
    """A collection error or crash is a real signal, not a ratchet case."""
    with tempfile.TemporaryDirectory() as d:
        sd._write_baseline(d, 12)
        monkeypatch.setattr(subprocess, "run", _patched("INTERNALERROR> boom", 3))
        assert sd.canary_gate(d) is False


def test_timeout_fails_closed(monkeypatch):
    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=1)
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr(subprocess, "run", _boom)
        assert sd.canary_gate(d) is False
