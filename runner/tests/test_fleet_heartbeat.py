#!/usr/bin/env python3
"""
Behavioural tests for machine + pipeline heartbeat alerts (directive 2026-08-02, §2).

Each test pins a property whose absence extended the incident:
  - a machine silent >30m must PAGE (Mac 2 was down half a day, unnoticed)
  - a restarted runner must not look like a second dead machine (runner_id is PID-based)
  - file-vs-DB pressure divergence must be REPORTED, not silently absorbed (false train-stale)
  - a missing .runner_boot_commit must be caught (self_deploy goes blind without it)
  - recovery mode must warn past its window and revert itself once the backlog is drained
  - the sustain clock must reset if the queue climbs again (no flapping release cadence)
"""
import os
import sys
import json
import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fleet_heartbeat as fh  # noqa: E402


def _iso(minutes_ago=0, hours_ago=0):
    stamp = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(minutes=minutes_ago, hours=hours_ago))
    return stamp.isoformat()


# ── machine liveness ─────────────────────────────────────────────────────────

def test_silent_machine_is_flagged_down(monkeypatch):
    monkeypatch.setattr(fh, "_fleet_control_ages", lambda: {})
    snap = fh.machines(rows=[
        {"hostname": "mac-1", "runner_id": "r1", "active_tasks": 3, "last_seen": _iso(minutes_ago=1)},
        {"hostname": "mac-2", "runner_id": "r2", "active_tasks": 0, "last_seen": _iso(hours_ago=6)},
    ])
    by_host = {m["hostname"]: m for m in snap["machines"]}
    assert by_host["mac-1"]["down"] is False
    assert by_host["mac-2"]["down"] is True


def test_silent_machine_pages_the_operator(monkeypatch):
    """The alert that did not exist on 2026-08-02."""
    monkeypatch.setattr(fh, "_fleet_control_ages", lambda: {})
    sent = []
    snap = fh.machines(rows=[
        {"hostname": "mac-2", "runner_id": "r2", "active_tasks": 0, "last_seen": _iso(hours_ago=6)},
    ])
    alerts = fh.check_machines(snap, notifier=sent.append)
    assert len(alerts) == 1
    assert "mac-2" in alerts[0] and "silent" in alerts[0]
    assert sent and sent[0].startswith("[fleet-heartbeat]")


def test_live_machine_does_not_page(monkeypatch):
    monkeypatch.setattr(fh, "_fleet_control_ages", lambda: {})
    snap = fh.machines(rows=[
        {"hostname": "mac-1", "runner_id": "r1", "active_tasks": 1, "last_seen": _iso(minutes_ago=2)},
    ])
    assert fh.check_machines(snap, notifier=lambda m: None) == []


def test_restarted_runner_is_one_machine_not_two(monkeypatch):
    """runner_id is PID-based, so restarts create rows. Liveness is per MACHINE.

    Collapsing on runner_id instead would show every previous PID as a dead machine and
    page continuously — an alert that cries wolf gets muted, which is how real outages
    get missed.
    """
    monkeypatch.setattr(fh, "_fleet_control_ages", lambda: {})
    snap = fh.machines(rows=[
        {"hostname": "mac-1", "runner_id": "pid-100", "active_tasks": 0, "last_seen": _iso(hours_ago=9)},
        {"hostname": "mac-1", "runner_id": "pid-200", "active_tasks": 0, "last_seen": _iso(hours_ago=4)},
        {"hostname": "mac-1", "runner_id": "pid-300", "active_tasks": 2, "last_seen": _iso(minutes_ago=1)},
    ])
    assert len(snap["machines"]) == 1
    assert snap["machines"][0]["down"] is False
    assert fh.check_machines(snap, notifier=lambda m: None) == []


def test_fleet_control_ack_age_is_reported(monkeypatch):
    """A machine can heartbeat while having stopped ACTING on fleet_control."""
    monkeypatch.setattr(fh, "_fleet_control_ages", lambda: {"mac-1": 12.0})
    snap = fh.machines(rows=[
        {"hostname": "mac-1", "runner_id": "r1", "active_tasks": 0, "last_seen": _iso(minutes_ago=1)},
    ])
    assert snap["machines"][0]["last_fleet_control_min"] == 12.0


def test_rows_without_a_timestamp_are_ignored(monkeypatch):
    monkeypatch.setattr(fh, "_fleet_control_ages", lambda: {})
    snap = fh.machines(rows=[{"hostname": "mac-9", "runner_id": "r", "last_seen": None}])
    assert snap["machines"] == []


# ── pressure file vs DB (the false train-stale bug class) ────────────────────

def test_pressure_divergence_is_detected(monkeypatch, tmp_path):
    """merge_train wrote the DB; sentinel watched the file; nothing compared them."""
    stale_file = tmp_path / "merge_train_pressure.json"
    stale_file.write_text("{}")
    old = datetime.datetime.now().timestamp() - (6 * 3600)
    os.utime(str(stale_file), (old, old))
    monkeypatch.setattr(fh, "PRESSURE_FILE", str(stale_file))
    monkeypatch.setattr(fh, "_control_get",
                        lambda key: {"updated_at": _iso(minutes_ago=2)})
    check = fh.selftest_pressure_consistency()
    assert check["ok"] is False
    assert "skew" in check["detail"]


def test_pressure_agreement_passes(monkeypatch, tmp_path):
    fresh = tmp_path / "merge_train_pressure.json"
    fresh.write_text("{}")
    monkeypatch.setattr(fh, "PRESSURE_FILE", str(fresh))
    monkeypatch.setattr(fh, "_control_get",
                        lambda key: {"updated_at": _iso(minutes_ago=1)})
    assert fh.selftest_pressure_consistency()["ok"] is True


def test_missing_pressure_file_is_a_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(fh, "PRESSURE_FILE", str(tmp_path / "nope.json"))
    monkeypatch.setattr(fh, "_control_get",
                        lambda key: {"updated_at": _iso(minutes_ago=1)})
    check = fh.selftest_pressure_consistency()
    assert check["ok"] is False
    assert "does not exist" in check["detail"]


def test_no_pressure_anywhere_is_unknown_not_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(fh, "PRESSURE_FILE", str(tmp_path / "nope.json"))
    monkeypatch.setattr(fh, "_control_get", lambda key: None)
    assert fh.selftest_pressure_consistency()["ok"] is None


# ── boot commit ──────────────────────────────────────────────────────────────

def test_missing_boot_commit_is_caught(monkeypatch, tmp_path):
    monkeypatch.setattr(fh, "BOOT_COMMIT_FILES", (str(tmp_path / "absent"),))
    check = fh.selftest_boot_commit()
    assert check["ok"] is False
    assert "self_deploy" in check["detail"]


def test_empty_boot_commit_is_caught(monkeypatch, tmp_path):
    path = tmp_path / ".runner_boot_commit"
    path.write_text("   \n")
    monkeypatch.setattr(fh, "BOOT_COMMIT_FILES", (str(path),))
    check = fh.selftest_boot_commit()
    assert check["ok"] is False
    assert "empty" in check["detail"]


def test_present_boot_commit_passes(monkeypatch, tmp_path):
    path = tmp_path / ".runner_boot_commit"
    path.write_text("abc123def456\n")
    monkeypatch.setattr(fh, "BOOT_COMMIT_FILES", (str(path),))
    check = fh.selftest_boot_commit()
    assert check["ok"] is True
    assert check["sha"] == "abc123def456"


# ── release-train recovery mode ──────────────────────────────────────────────

def _env(tmp_path, body):
    path = tmp_path / ".env"
    path.write_text(body)
    return str(path)


def test_env_override_is_parsed(monkeypatch, tmp_path):
    monkeypatch.setattr(fh, "ENV_FILE", _env(
        tmp_path, "# comment\nFOO=bar\nRELEASE_MIN_BATCH=1\nBAZ=\"2\"\n"))
    assert fh._env_override("RELEASE_MIN_BATCH") == "1"
    assert fh._env_override("BAZ") == "2"
    assert fh._env_override("ABSENT") is None


def test_recovery_mode_warns_past_the_window(monkeypatch, tmp_path):
    monkeypatch.setattr(fh, "ENV_FILE", _env(tmp_path, "RELEASE_MIN_BATCH=1\n"))
    monkeypatch.setattr(fh, "_control_get",
                        lambda key: {"value": json.dumps(_iso(hours_ago=100))})
    monkeypatch.setattr(fh, "_control_set", lambda k, v: True)
    check = fh.selftest_release_env()
    assert check["ok"] is False
    assert "recovery mode active" in check["detail"]


def test_recovery_mode_within_window_passes(monkeypatch, tmp_path):
    monkeypatch.setattr(fh, "ENV_FILE", _env(tmp_path, "RELEASE_MIN_BATCH=1\n"))
    monkeypatch.setattr(fh, "_control_get",
                        lambda key: {"value": json.dumps(_iso(hours_ago=5))})
    monkeypatch.setattr(fh, "_control_set", lambda k, v: True)
    assert fh.selftest_release_env()["ok"] is True


def test_not_in_recovery_mode_passes(monkeypatch, tmp_path):
    monkeypatch.setattr(fh, "ENV_FILE", _env(tmp_path, "RELEASE_MIN_BATCH=10\n"))
    monkeypatch.delenv("RELEASE_MIN_BATCH", raising=False)
    assert fh.selftest_release_env()["ok"] is True


# ── auto-revert ──────────────────────────────────────────────────────────────

def test_auto_revert_removes_the_override_after_the_sustain_window(monkeypatch, tmp_path):
    env_path = _env(tmp_path, "FOO=bar\nRELEASE_MIN_BATCH=1\nBAZ=qux\n")
    monkeypatch.setattr(fh, "ENV_FILE", env_path)
    monkeypatch.setattr(fh, "_control_get",
                        lambda key: {"value": json.dumps(_iso(hours_ago=30))})
    monkeypatch.setattr(fh, "_control_set", lambda k, v: True)
    sent = []
    out = fh.auto_revert_release_min_batch(counts={"p1": 3, "p2": 12},
                                           notifier=sent.append)
    assert out["reverted"] is True
    body = open(env_path).read()
    assert "RELEASE_MIN_BATCH" not in body
    assert "FOO=bar" in body and "BAZ=qux" in body, "unrelated env keys must survive"
    assert sent and "default batching restored" in sent[0]


def test_auto_revert_waits_out_the_sustain_window(monkeypatch, tmp_path):
    env_path = _env(tmp_path, "RELEASE_MIN_BATCH=1\n")
    monkeypatch.setattr(fh, "ENV_FILE", env_path)
    monkeypatch.setattr(fh, "_control_get",
                        lambda key: {"value": json.dumps(_iso(hours_ago=3))})
    monkeypatch.setattr(fh, "_control_set", lambda k, v: True)
    out = fh.auto_revert_release_min_batch(counts={"p1": 3})
    assert out["reverted"] is False
    assert "RELEASE_MIN_BATCH=1" in open(env_path).read()


def test_deep_queue_resets_the_clock_and_keeps_recovery_mode(monkeypatch, tmp_path):
    """A queue that climbs again must restart the clock, or the cadence would flap."""
    monkeypatch.setattr(fh, "ENV_FILE", _env(tmp_path, "RELEASE_MIN_BATCH=1\n"))
    writes = {}
    monkeypatch.setattr(fh, "_control_get",
                        lambda key: {"value": json.dumps(_iso(hours_ago=30))})
    monkeypatch.setattr(fh, "_control_set",
                        lambda k, v: writes.__setitem__(k, v) or True)
    out = fh.auto_revert_release_min_batch(counts={"p1": 900})
    assert out["reverted"] is False
    assert writes.get("release_min_batch_below_floor_since") is None, "clock not reset"


def test_auto_revert_noop_when_not_in_recovery_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(fh, "ENV_FILE", _env(tmp_path, "RELEASE_MIN_BATCH=10\n"))
    out = fh.auto_revert_release_min_batch(counts={"p1": 1})
    assert out["reverted"] is False
    assert "not in recovery mode" in out["detail"]


def test_auto_revert_dry_run_does_not_touch_the_file(monkeypatch, tmp_path):
    env_path = _env(tmp_path, "RELEASE_MIN_BATCH=1\n")
    monkeypatch.setattr(fh, "ENV_FILE", env_path)
    monkeypatch.setattr(fh, "_control_get",
                        lambda key: {"value": json.dumps(_iso(hours_ago=30))})
    monkeypatch.setattr(fh, "_control_set", lambda k, v: True)
    out = fh.auto_revert_release_min_batch(counts={"p1": 1}, apply=False)
    assert out["reverted"] is False
    assert "RELEASE_MIN_BATCH=1" in open(env_path).read()


def test_consistency_selftests_returns_all_three(monkeypatch, tmp_path):
    monkeypatch.setattr(fh, "PRESSURE_FILE", str(tmp_path / "nope.json"))
    monkeypatch.setattr(fh, "BOOT_COMMIT_FILES", (str(tmp_path / "absent"),))
    monkeypatch.setattr(fh, "ENV_FILE", _env(tmp_path, "RELEASE_MIN_BATCH=10\n"))
    monkeypatch.delenv("RELEASE_MIN_BATCH", raising=False)
    monkeypatch.setattr(fh, "_control_get", lambda key: None)
    names = [c["name"] for c in fh.consistency_selftests(notifier=lambda m: None)]
    assert names == ["pressure_file_vs_db", "boot_commit_file", "release_min_batch_recovery"]
