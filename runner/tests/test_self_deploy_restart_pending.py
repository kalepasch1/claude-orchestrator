"""A commit that already passed the gate must not be re-gated while it waits to deploy.

The runner exits cooperatively BETWEEN tasks, so minutes can pass between "restart
requested" and the process actually swapping. self_deploy runs every 180s. Without this
guard it re-ran the full ~1000-test bounded gate for the same already-green commit, again
and again, on a machine the fleet has already saturated.

Observed 2026-08-18 on mac-lan:

    self_deploy: canary pinned to a clean checkout of c9570b0c
    self_deploy: restart requested into c9570b0c          <- green
    self_deploy: canary pinned to a clean checkout of c9570b0c
    self_deploy: bounded behavior gate timed out after 300s
    self_deploy: BLOCKED — tests failing; filing approvals card   <- same commit, 3 min later

The redundant run is what created the load that made it time out, and the card it filed
said "tests failing" about code that had just passed.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import self_deploy  # noqa: E402

HEAD = "c9570b0ce37693fb0c5d49029bdfee6e1d70ab1a"
OTHER = "aaaa1111bbbb2222cccc3333dddd4444eeee5555"


@pytest.fixture
def flag(tmp_path, monkeypatch):
    path = tmp_path / ".restart_requested"
    monkeypatch.setattr(self_deploy, "RESTART_FLAG", str(path))
    return path


def test_pending_when_the_flag_names_this_head(flag):
    flag.write_text(f"2026-08-18T00:00:00 new code {HEAD[:8]} passed canary gate\n")
    assert self_deploy.restart_pending_for(HEAD) is True


def test_not_pending_for_a_different_head(flag):
    flag.write_text(f"2026-08-18T00:00:00 new code {OTHER[:8]} passed canary gate\n")
    assert self_deploy.restart_pending_for(HEAD) is False


def test_not_pending_without_a_flag(flag):
    assert self_deploy.restart_pending_for(HEAD) is False


def test_not_pending_without_a_head(flag):
    flag.write_text(f"anything {HEAD[:8]}\n")
    assert self_deploy.restart_pending_for("") is False


def test_a_stale_flag_stops_suppressing_the_gate(flag, monkeypatch):
    """A restart that never happens must not hide staleness forever."""
    flag.write_text(f"2026-08-18T00:00:00 new code {HEAD[:8]} passed canary gate\n")
    old = time.time() - self_deploy.RESTART_PENDING_MAX_AGE - 60
    os.utime(str(flag), (old, old))

    assert self_deploy.restart_pending_for(HEAD) is False


def _stub_flow(monkeypatch, head, gate_result=True):
    calls = {"gate": 0, "restart": 0}
    monkeypatch.setattr(self_deploy, "reconcile_origin", lambda repo: {"action": "none"})
    monkeypatch.setattr(self_deploy, "check_new_code", lambda repo: {
        "running_commit": OTHER, "head_commit": head, "stale": True, "unknown": False})
    monkeypatch.setattr(self_deploy, "canary_gate",
                        lambda *a, **k: (calls.__setitem__("gate", calls["gate"] + 1),
                                         gate_result)[1])
    monkeypatch.setattr(self_deploy, "request_restart",
                        lambda reason: calls.__setitem__("restart", calls["restart"] + 1))
    return calls


def test_maybe_deploy_skips_the_gate_while_a_restart_is_pending(flag, monkeypatch):
    flag.write_text(f"2026-08-18T00:00:00 new code {HEAD[:8]} passed canary gate\n")
    calls = _stub_flow(monkeypatch, HEAD)

    result = self_deploy.maybe_deploy("/repo")

    assert result["reason"] == "restart_pending"
    assert result["deployed"] is False
    assert calls["gate"] == 0, "re-running a gate this commit already passed is the bug"
    assert calls["restart"] == 0, "and it must not re-request the restart either"


def test_maybe_deploy_still_gates_a_head_the_flag_does_not_name(flag, monkeypatch):
    """New code landing while an older restart is queued must still be verified."""
    flag.write_text(f"2026-08-18T00:00:00 new code {OTHER[:8]} passed canary gate\n")
    calls = _stub_flow(monkeypatch, HEAD)

    result = self_deploy.maybe_deploy("/repo")

    assert result["reason"] == "restart_requested"
    assert calls["gate"] == 1
    assert calls["restart"] == 1


def test_a_red_gate_still_blocks(flag, monkeypatch):
    calls = _stub_flow(monkeypatch, HEAD, gate_result=False)
    monkeypatch.setattr(self_deploy, "_file_blocked_card", lambda: None)

    result = self_deploy.maybe_deploy("/repo")

    assert result["reason"] == "canary_failed"
    assert calls["restart"] == 0
