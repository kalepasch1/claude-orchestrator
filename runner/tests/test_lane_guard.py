#!/usr/bin/env python3
"""
Behavioural tests for the lane + daemon immune system (operator directive 2026-08-02).

These assert the properties whose absence caused the incident, not the implementation:
  - a wedged lane is killed, and its DESCENDANTS die with it (the bug subprocess.run had)
  - a silent lane is reaped before it burns the whole wall clock
  - a second copy of an interval script cannot start while the first holds the lock
  - the lock is released when the holder exits, including via exception
  - telemetry reports lane counts/ages and alerts fire at the documented thresholds
"""
import os
import sys
import time
import signal
import subprocess

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lane_guard  # noqa: E402


# ── wall clock + heartbeat ───────────────────────────────────────────────────

def test_wall_clock_kills_a_wedged_lane():
    t0 = time.time()
    with pytest.raises(subprocess.TimeoutExpired):
        lane_guard.run_guarded(["sleep", "60"], timeout=2, grace_s=60)
    assert time.time() - t0 < 20, "guard did not return promptly after the wall clock"


def test_heartbeat_reaps_a_silent_lane_before_the_wall_clock():
    """A lane that stops producing output is reaped early — the wedge signature."""
    t0 = time.time()
    with pytest.raises(subprocess.TimeoutExpired):
        lane_guard.run_guarded(["sleep", "60"], timeout=300, grace_s=2)
    elapsed = time.time() - t0
    assert elapsed < 20, "heartbeat reap took {0}s".format(elapsed)


def test_output_activity_defers_the_heartbeat_reap():
    """A chatty-but-slow lane must NOT be reaped: silence is the signal, not duration."""
    script = "for i in 1 2 3 4 5 6; do echo tick; sleep 0.5; done"
    proc = lane_guard.run_guarded(["bash", "-c", script], timeout=60, grace_s=2)
    assert proc.returncode == 0
    assert proc.stdout.count("tick") == 6


def test_descendants_die_with_the_lane():
    """The actual 2026-08-02 root cause.

    subprocess.run(timeout=) kills only the direct child. The `claude` binary's children
    survived and kept holding RAM, which is how 64 lanes became zombies while the runner
    believed it had reaped them. run_guarded uses start_new_session + killpg, so the whole
    group dies. Here the parent shell exits immediately and leaves a long-lived grandchild;
    the grandchild must be dead once the guard returns.
    """
    marker = "/tmp/lane_guard_descendant_{0}".format(os.getpid())
    script = "sleep 120 & echo $! > {0}; sleep 120".format(marker)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            lane_guard.run_guarded(["bash", "-c", script], timeout=3, grace_s=60)
        time.sleep(1)
        with open(marker) as fh:
            grandchild = int(fh.read().strip())
        with pytest.raises(OSError):
            os.kill(grandchild, 0)          # ESRCH == the descendant is gone
    finally:
        try:
            os.remove(marker)
        except OSError:
            pass


def test_successful_lane_returns_completed_process():
    proc = lane_guard.run_guarded(["echo", "hello"], timeout=30)
    assert proc.returncode == 0
    assert "hello" in proc.stdout


def test_kill_process_tree_refuses_to_kill_its_own_group():
    """A guard that can shoot the runner itself is worse than no guard."""
    assert lane_guard.kill_process_tree(os.getpid()) is False


# ── per-task-class wall clocks ───────────────────────────────────────────────

def test_class_timeout_defaults_to_45_minutes():
    assert lane_guard.class_timeout("unmapped-class") == 45 * 60


def test_class_timeout_is_per_class():
    assert lane_guard.class_timeout("canary") < lane_guard.class_timeout("build")
    assert lane_guard.class_timeout("feature") > lane_guard.class_timeout("bugfix")


def test_class_timeout_env_override(monkeypatch):
    monkeypatch.setenv("ORCH_LANE_TIMEOUT_CANARY", "7")
    assert lane_guard.class_timeout("canary") == 7 * 60


def test_heartbeat_grace_never_exceeds_the_wall_clock():
    for cls in ("canary", "build", "feature", None):
        assert lane_guard.heartbeat_grace(cls) <= lane_guard.class_timeout(cls)


# ── single-instance locks ────────────────────────────────────────────────────

def test_second_copy_cannot_start_while_the_first_holds_the_lock(tmp_path, monkeypatch):
    """The legal_docket leak: 14 concurrent copies on a 30-minute interval."""
    monkeypatch.setattr(lane_guard, "LOCK_DIR", str(tmp_path))
    with lane_guard.single_instance("legal_docket", interval_s=1800):
        assert lane_guard.lock_held("legal_docket") is True
        with pytest.raises(lane_guard.AlreadyRunning):
            with lane_guard.single_instance("legal_docket", interval_s=1800):
                pytest.fail("a second copy acquired the lock")


def test_lock_is_released_on_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(lane_guard, "LOCK_DIR", str(tmp_path))
    with lane_guard.single_instance("foulkon_sync", interval_s=600):
        pass
    assert lane_guard.lock_held("foulkon_sync") is False
    with lane_guard.single_instance("foulkon_sync", interval_s=600) as held:
        assert held is True


def test_lock_is_released_when_the_holder_raises(tmp_path, monkeypatch):
    """A crashing tick must not wedge the lock shut for every future tick."""
    monkeypatch.setattr(lane_guard, "LOCK_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        with lane_guard.single_instance("expert_corps", interval_s=60):
            raise ValueError("tick blew up")
    assert lane_guard.lock_held("expert_corps") is False


def test_non_raising_mode_reports_busy(tmp_path, monkeypatch):
    monkeypatch.setattr(lane_guard, "LOCK_DIR", str(tmp_path))
    with lane_guard.single_instance("benchmark_redlines", interval_s=3600):
        second = lane_guard.single_instance("benchmark_redlines", raise_on_busy=False)
        assert second.__enter__() is False


def test_max_runtime_defaults_to_interval_times_1_5(tmp_path, monkeypatch):
    monkeypatch.setattr(lane_guard, "LOCK_DIR", str(tmp_path))
    lock = lane_guard.single_instance("some_daemon", interval_s=1800)
    assert lock.max_runtime_s == 2700


def test_locks_are_independent_per_name(tmp_path, monkeypatch):
    monkeypatch.setattr(lane_guard, "LOCK_DIR", str(tmp_path))
    with lane_guard.single_instance("daemon_a"):
        with lane_guard.single_instance("daemon_b") as held:
            assert held is True


# ── telemetry + alerting ─────────────────────────────────────────────────────

@pytest.mark.parametrize("etime,expected", [
    ("05", 0), ("45", 0), ("02:30", 2), ("10:00", 10),
    ("01:30:00", 90), ("2-03:00:00", 3060),
])
def test_etime_parsing(etime, expected):
    """lane_medic.sh collapsed any day-old process to a sentinel; the histogram needs real ages.

    Ages floor rather than round: the value feeds kill thresholds, so under-reporting is
    the safe error direction.
    """
    assert lane_guard.etime_minutes(etime) == expected


def test_age_histogram_buckets():
    lanes = [{"age_min": 5}, {"age_min": 20}, {"age_min": 60}, {"age_min": 300}, {"age_min": 301}]
    assert lane_guard.age_histogram(lanes) == {
        "lt_15m": 1, "15_45m": 1, "45_90m": 1, "gt_90m": 2}


def test_telemetry_reports_the_dashboard_fields():
    snap = lane_guard.telemetry()
    for key in ("lane_count", "lane_throttle", "lane_age_histogram", "reaps_last_hour",
                "mem_gate_open", "mem_gate_closed_min", "free_ram_gb", "interval_daemons"):
        assert key in snap, "dashboard field {0} missing".format(key)
    assert isinstance(snap["lane_count"], int)


def test_alert_fires_when_lanes_exceed_throttle_plus_slack():
    sent = []
    snap = {"lane_count": 20, "lane_throttle": 8, "oldest_lane_min": 300,
            "mem_gate_open": True, "mem_gate_closed_min": 0, "mem_gate_reason": "ok",
            "free_ram_gb": 30, "ram_floor_gb": 8, "interval_daemons": {}}
    alerts = lane_guard.check_and_alert(snap, notifier=sent.append)
    assert len(alerts) == 1 and "lane leak" in alerts[0]
    assert sent and sent[0].startswith("[fleet-immune]")


def test_no_alert_at_or_below_the_ceiling():
    snap = {"lane_count": 13, "lane_throttle": 8, "oldest_lane_min": 10,
            "mem_gate_open": True, "mem_gate_closed_min": 0, "mem_gate_reason": "ok",
            "free_ram_gb": 30, "ram_floor_gb": 8, "interval_daemons": {}}
    assert lane_guard.check_and_alert(snap, notifier=lambda m: None) == []


def test_alert_fires_when_mem_gate_stuck_closed():
    """Mac 2 was down half a day unnoticed; a closed gate must page, not sit silent."""
    snap = {"lane_count": 1, "lane_throttle": 8, "oldest_lane_min": 1,
            "mem_gate_open": False, "mem_gate_closed_min": 20,
            "mem_gate_reason": "low RAM", "free_ram_gb": 2, "ram_floor_gb": 8,
            "interval_daemons": {}}
    alerts = lane_guard.check_and_alert(snap, notifier=lambda m: None)
    assert any("mem-gate closed" in a for a in alerts)


def test_no_mem_gate_alert_before_the_window():
    snap = {"lane_count": 1, "lane_throttle": 8, "oldest_lane_min": 1,
            "mem_gate_open": False, "mem_gate_closed_min": 5,
            "mem_gate_reason": "low RAM", "free_ram_gb": 2, "ram_floor_gb": 8,
            "interval_daemons": {}}
    assert lane_guard.check_and_alert(snap, notifier=lambda m: None) == []


def test_duplicate_daemon_copies_alert():
    snap = {"lane_count": 1, "lane_throttle": 8, "oldest_lane_min": 1,
            "mem_gate_open": True, "mem_gate_closed_min": 0, "mem_gate_reason": "ok",
            "free_ram_gb": 30, "ram_floor_gb": 8,
            "interval_daemons": {"legal_docket.py": {"count": 14, "oldest_min": 600}}}
    alerts = lane_guard.check_and_alert(snap, notifier=lambda m: None)
    assert any("legal_docket.py" in a and "14 concurrent" in a for a in alerts)


def test_reap_sweep_is_dry_runnable():
    """The sweep must be inspectable without killing anything."""
    assert isinstance(lane_guard.reap_zombie_lanes(max_age_min=1, dry_run=True), list)
    assert isinstance(lane_guard.reap_stuck_daemons(dry_run=True), list)


def test_cli_telemetry_returns_json():
    out = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                      "lane_guard.py"), "telemetry"],
        capture_output=True, text=True, timeout=90)
    assert out.returncode == 0
    import json
    assert "lane_count" in json.loads(out.stdout)
