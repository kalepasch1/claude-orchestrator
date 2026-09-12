#!/usr/bin/env python3
"""Integration tests for zombie_reap_cycle — the periodic reaper wired into the runner.

The acceptance behaviour this file exists to prove: a task with an old heartbeat is
marked FAILED after the reaper runs, and the whole thing can be switched off without
a code change.

These are integration tests in the sense that matters here — they exercise the real
`zombie_reap_cycle` against the real `zombie_reaper`, joined by an in-memory store
that implements `db.py`'s two-method surface. Nothing is mocked between detection and
the FAILED write, so a break anywhere in that pipeline fails these tests.
"""
import os
import sys
import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import zombie_reap_cycle  # noqa: E402
import zombie_reaper  # noqa: E402


# --------------------------------------------------------------------------- fakes

class FakeStore:
    """In-memory stand-in for runner/db.py. Supports the filters the cycle uses."""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.updates = []
        self.select_calls = []
        self.fail_select = False
        self.fail_update = False

    def select(self, table, params):
        self.select_calls.append((table, dict(params or {})))
        if self.fail_select:
            raise RuntimeError("store unavailable")
        out = []
        for row in self.rows:
            match = True
            for key, raw in (params or {}).items():
                if key in ("select", "order", "limit"):
                    continue
                value = str(raw)
                if value.startswith("eq."):
                    if str(row.get(key)) != value[3:]:
                        match = False
                        break
            if match:
                out.append(dict(row))
        try:
            limit = int((params or {}).get("limit") or 0)
        except (TypeError, ValueError):
            limit = 0
        return out[:limit] if limit else out

    def update(self, table, match, patch):
        if self.fail_update:
            raise RuntimeError("update rejected")
        self.updates.append((table, dict(match), dict(patch)))
        for row in self.rows:
            if all(str(row.get(k)) == str(v) for k, v in (match or {}).items()):
                row.update(patch)
        return [dict(match)]

    def state_of(self, task_id):
        for row in self.rows:
            if str(row.get("id")) == str(task_id):
                return row.get("state")
        return None


def _ago(seconds):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=seconds)).isoformat()


def _task(task_id, age_s, **over):
    row = {
        "id": task_id,
        "slug": f"slug-{task_id}",
        "state": "RUNNING",
        "note": "prior note",
        "attempt": 4,
        "account": "Mac.lan-1234",
        "updated_at": _ago(age_s),
    }
    row.update(over)
    return row


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Every ORCH_ZOMBIE_* knob cleared, and termination armed, so tests read defaults."""
    for key in list(os.environ):
        if key.startswith("ORCH_ZOMBIE"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ORCH_ZOMBIE_TERMINATE_ENABLED", "true")
    zombie_reap_cycle.reset()
    yield
    zombie_reap_cycle.reset()


def _cycle(store):
    """A cycle bound to `store` and the real reaper, with a controllable clock."""
    clock = {"t": 1000.0}
    reaper = zombie_reaper.ZombieReaper()
    cyc = zombie_reap_cycle.ZombieReapCycle(store=store, reaper=reaper,
                                            clock=lambda: clock["t"])
    return cyc, clock


# ------------------------------------------------------------------- acceptance

def test_old_heartbeat_task_is_marked_failed():
    """THE acceptance test: stale heartbeat in, FAILED out."""
    store = FakeStore([_task("zombie-1", age_s=9999)])
    cyc, _ = _cycle(store)

    result = cyc.run_once()

    assert result["ran"] is True
    assert result["detected"] == ["zombie-1"]
    assert result["terminated"] == ["zombie-1"]
    assert store.state_of("zombie-1") == "FAILED"


def test_terminated_note_preserves_prior_note_and_reason():
    store = FakeStore([_task("zombie-1", age_s=9999)])
    cyc, _ = _cycle(store)

    cyc.run_once()

    _, _, patch = store.updates[-1]
    assert "prior note" in patch["note"]
    assert "zombie-reaper" in patch["note"]
    assert patch["state"] == "FAILED"


def test_fresh_heartbeat_task_is_left_running():
    store = FakeStore([_task("healthy", age_s=10)])
    cyc, _ = _cycle(store)

    result = cyc.run_once()

    assert result["detected"] == []
    assert store.state_of("healthy") == "RUNNING"
    assert store.updates == []


def test_only_stale_tasks_are_terminated_in_a_mixed_queue():
    store = FakeStore([
        _task("healthy", age_s=30),
        _task("stale-a", age_s=9999),
        _task("borderline", age_s=zombie_reap_cycle.DEFAULT_HEARTBEAT_TTL_S - 60),
        _task("stale-b", age_s=20000),
    ])
    cyc, _ = _cycle(store)

    result = cyc.run_once()

    assert set(result["terminated"]) == {"stale-a", "stale-b"}
    assert store.state_of("healthy") == "RUNNING"
    assert store.state_of("borderline") == "RUNNING"


def test_non_running_tasks_are_never_touched():
    store = FakeStore([
        _task("done-old", age_s=9999, state="DONE"),
        _task("queued-old", age_s=9999, state="QUEUED"),
    ])
    cyc, _ = _cycle(store)

    result = cyc.run_once()

    assert result["detected"] == []
    assert store.state_of("done-old") == "DONE"
    assert store.state_of("queued-old") == "QUEUED"


def test_cowork_accounts_are_skipped():
    """Interactive Cowork sessions heartbeat themselves; disposing of them
    would fail work that is genuinely in flight."""
    store = FakeStore([_task("cw", age_s=9999, account="cowork-executor-v6-1")])
    cyc, _ = _cycle(store)

    assert cyc.run_once()["detected"] == []
    assert store.state_of("cw") == "RUNNING"


# ----------------------------------------------------------------- the on/off flag

def test_disabled_flag_makes_the_cycle_a_no_op(monkeypatch):
    monkeypatch.setenv("ORCH_ZOMBIE_REAPER_ENABLED", "false")
    store = FakeStore([_task("zombie-1", age_s=9999)])
    cyc, _ = _cycle(store)

    result = cyc.run_once()

    assert result["ran"] is False
    assert result["reason"] == "disabled"
    assert store.state_of("zombie-1") == "RUNNING"
    assert store.select_calls == []


def test_flag_can_be_toggled_back_on_without_code_change(monkeypatch):
    store = FakeStore([_task("zombie-1", age_s=9999)])
    cyc, _ = _cycle(store)

    monkeypatch.setenv("ORCH_ZOMBIE_REAPER_ENABLED", "false")
    assert cyc.run_once()["ran"] is False

    monkeypatch.setenv("ORCH_ZOMBIE_REAPER_ENABLED", "true")
    assert cyc.run_once()["terminated"] == ["zombie-1"]
    assert store.state_of("zombie-1") == "FAILED"


@pytest.mark.parametrize("raw,expected", [
    ("true", True), ("1", True), ("yes", True), ("on", True),
    ("false", False), ("0", False), ("no", False), ("off", False),
])
def test_enabled_flag_parses_common_boolean_spellings(monkeypatch, raw, expected):
    monkeypatch.setenv("ORCH_ZOMBIE_REAPER_ENABLED", raw)
    assert zombie_reap_cycle.enabled() is expected


def test_enabled_defaults_to_true_when_unset():
    assert zombie_reap_cycle.enabled() is True


# --------------------------------------------------------------------- the interval

def test_interval_defaults_to_thirty_seconds():
    assert zombie_reap_cycle.interval_s() == 30


def test_interval_is_configurable(monkeypatch):
    monkeypatch.setenv("ORCH_ZOMBIE_REAPER_INTERVAL_S", "120")
    assert zombie_reap_cycle.interval_s() == 120


@pytest.mark.parametrize("bad", ["0", "-5", "", "not-a-number"])
def test_bad_interval_falls_back_to_default_rather_than_hot_looping(monkeypatch, bad):
    monkeypatch.setenv("ORCH_ZOMBIE_REAPER_INTERVAL_S", bad)
    assert zombie_reap_cycle.interval_s() == 30


def test_second_call_inside_the_interval_does_not_re_query():
    store = FakeStore([_task("zombie-1", age_s=9999)])
    cyc, clock = _cycle(store)

    cyc.run_once()
    calls_after_first = len(store.select_calls)

    clock["t"] += 5  # still inside the 30s window
    second = cyc.run_once()

    assert second["ran"] is False
    assert second["reason"] == "not-due"
    assert len(store.select_calls) == calls_after_first


def test_cycle_runs_again_once_the_interval_elapses():
    store = FakeStore([_task("zombie-1", age_s=9999)])
    cyc, clock = _cycle(store)

    cyc.run_once()
    store.rows.append(_task("zombie-2", age_s=9999))

    clock["t"] += 31
    second = cyc.run_once()

    assert second["ran"] is True
    assert second["terminated"] == ["zombie-2"]
    assert store.state_of("zombie-2") == "FAILED"


def test_force_bypasses_the_interval_gate():
    store = FakeStore([_task("zombie-1", age_s=9999)])
    cyc, _ = _cycle(store)

    cyc.run_once()
    store.rows.append(_task("zombie-2", age_s=9999))

    assert cyc.run_once(force=True)["terminated"] == ["zombie-2"]


def test_first_call_is_always_due():
    cyc, _ = _cycle(FakeStore())
    assert cyc.due() is True


# ------------------------------------------------------------------ other knobs

def test_heartbeat_ttl_is_configurable(monkeypatch):
    monkeypatch.setenv("ORCH_ZOMBIE_REAPER_HEARTBEAT_TTL_S", "60")
    store = FakeStore([_task("recent", age_s=120)])
    cyc, _ = _cycle(store)

    assert cyc.run_once()["terminated"] == ["recent"]


def test_min_attempt_floor_defers_first_attempt_tasks(monkeypatch):
    monkeypatch.setenv("ORCH_ZOMBIE_REAPER_MIN_ATTEMPT", "3")
    store = FakeStore([
        _task("young-budget", age_s=9999, attempt=1),
        _task("spent-budget", age_s=9999, attempt=3),
    ])
    cyc, _ = _cycle(store)

    result = cyc.run_once()

    assert result["terminated"] == ["spent-budget"]
    assert store.state_of("young-budget") == "RUNNING"


def test_max_per_cycle_caps_a_fleet_wide_outage(monkeypatch):
    monkeypatch.setenv("ORCH_ZOMBIE_REAPER_MAX_PER_CYCLE", "2")
    store = FakeStore([_task(f"z{i}", age_s=9999) for i in range(10)])
    cyc, _ = _cycle(store)

    assert len(cyc.run_once()["terminated"]) == 2


def test_stats_reports_current_configuration(monkeypatch):
    monkeypatch.setenv("ORCH_ZOMBIE_REAPER_INTERVAL_S", "45")
    stats = zombie_reap_cycle.stats()
    assert stats["interval_s"] == 45
    assert stats["enabled"] is True
    assert "heartbeat_ttl_s" in stats


# ------------------------------------------------------------------- fail-soft

def test_store_read_failure_terminates_nothing_and_does_not_raise():
    store = FakeStore([_task("zombie-1", age_s=9999)])
    store.fail_select = True
    cyc, _ = _cycle(store)

    result = cyc.run_once()

    assert result["ran"] is True
    assert result["detected"] == []
    assert store.state_of("zombie-1") == "RUNNING"


def test_store_write_failure_is_reported_not_raised():
    store = FakeStore([_task("zombie-1", age_s=9999)])
    store.fail_update = True
    cyc, _ = _cycle(store)

    result = cyc.run_once()

    assert result["errored"] == ["zombie-1"]
    assert result["terminated"] == []
    assert store.state_of("zombie-1") == "RUNNING"


def test_unparseable_heartbeat_is_never_treated_as_expired():
    store = FakeStore([_task("weird", age_s=9999, updated_at="not-a-timestamp")])
    cyc, _ = _cycle(store)

    assert cyc.run_once()["detected"] == []
    assert store.state_of("weird") == "RUNNING"


def test_missing_heartbeat_is_never_treated_as_expired():
    store = FakeStore([_task("blank", age_s=9999, updated_at="")])
    cyc, _ = _cycle(store)

    assert cyc.run_once()["detected"] == []


def test_rows_without_ids_are_skipped_without_crashing():
    store = FakeStore([_task("", age_s=9999), _task("good", age_s=9999)])
    cyc, _ = _cycle(store)

    assert cyc.run_once()["terminated"] == ["good"]


def test_non_integer_attempt_does_not_crash_detection(monkeypatch):
    monkeypatch.setenv("ORCH_ZOMBIE_REAPER_MIN_ATTEMPT", "0")
    store = FakeStore([_task("odd", age_s=9999, attempt="many")])
    cyc, _ = _cycle(store)

    assert cyc.run_once()["terminated"] == ["odd"]


def test_reaper_exception_leaves_tasks_running_and_reports_errored():
    class ExplodingReaper:
        def terminate_expired(self, *a, **k):
            raise RuntimeError("boom")

    store = FakeStore([_task("zombie-1", age_s=9999)])
    cyc = zombie_reap_cycle.ZombieReapCycle(store=store, reaper=ExplodingReaper(),
                                            clock=lambda: 0.0)

    result = cyc.run_once()

    assert result["errored"] == ["zombie-1"]
    assert store.state_of("zombie-1") == "RUNNING"


def test_empty_queue_is_a_clean_no_op():
    store = FakeStore([])
    cyc, _ = _cycle(store)

    result = cyc.run_once()

    assert result["ran"] is True
    assert result["detected"] == []
    assert store.updates == []


# ------------------------------------------------------- module-level singleton

def test_module_level_functions_delegate_to_the_singleton():
    zombie_reap_cycle.reset()
    store = FakeStore([_task("zombie-1", age_s=9999)])

    assert zombie_reap_cycle.due() is True
    assert zombie_reap_cycle.detect(store=store) == ["zombie-1"]

    result = zombie_reap_cycle.run_once(store=store, force=True)
    assert result["terminated"] == ["zombie-1"]
    assert store.state_of("zombie-1") == "FAILED"


def test_reset_clears_pacing_state():
    store = FakeStore([])
    zombie_reap_cycle.run_once(store=store, force=True)
    zombie_reap_cycle.reset()
    assert zombie_reap_cycle.due() is True


def test_dry_run_mode_reports_without_writing(monkeypatch):
    """ORCH_ZOMBIE_TERMINATE_ENABLED=false keeps the pipeline observable but inert."""
    monkeypatch.setenv("ORCH_ZOMBIE_TERMINATE_ENABLED", "false")
    store = FakeStore([_task("zombie-1", age_s=9999)])
    cyc, _ = _cycle(store)

    result = cyc.run_once()

    assert result["terminated"] == ["zombie-1"]
    assert store.updates == []
    assert store.state_of("zombie-1") == "RUNNING"
