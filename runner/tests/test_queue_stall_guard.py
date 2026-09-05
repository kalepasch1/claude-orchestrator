"""A fleet with a full queue and nothing running must say so.

WHY THIS EXISTS (2026-09-02). The runner requested a self-deploy restart, began draining
lanes, and never converged: MAX_PARALLEL was 3 so the drain threshold clamped to 3 // 4 =
0, three agent threads were stuck alive, and draining freezes new claims. The fleet
claimed nothing for 39 minutes:

    beethoven 112 QUEUED / 0 RUNNING     tomorrow 110 QUEUED / 0 RUNNING
    smarter    21 QUEUED / 0 RUNNING     apparently-law 18 QUEUED / 0 RUNNING
    ... 334 QUEUED across eleven projects, 0 RUNNING anywhere

Every existing signal looked healthy: the runner process was alive, its scheduler ticked
through every periodic job, and runner_guard saw a live pid. Nothing compared "work
waiting" with "work being done" -- the one comparison that catches this in a minute.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sentinel  # noqa: E402


class FakeDB:
    def __init__(self, queued, running):
        self.queued, self.running = queued, running

    def select(self, table, query=None):
        state = (query or {}).get("state", "")
        if state.endswith("QUEUED"):
            return [{"id": n} for n in range(self.queued)]
        if state.endswith("RUNNING"):
            return [{"id": n} for n in range(self.running)]
        return []


@pytest.fixture(autouse=True)
def wiring(monkeypatch):
    """Route the guard at a fake DB and capture what it logs, touching nothing live."""
    logged, emitted = [], []
    monkeypatch.setattr(sentinel, "log", lambda action, detail="": logged.append((action, detail)))
    monkeypatch.setattr(sentinel, "emit", lambda kind, **fields: emitted.append((kind, fields)))
    monkeypatch.setattr(sentinel, "QUEUE_STALL_PASSES", 3)
    monkeypatch.setattr(sentinel, "QUEUE_STALL_MIN_QUEUED", 5)
    monkeypatch.setattr(sentinel, "QUEUE_STALL_COOLDOWN_S", 0)
    return {"logged": logged, "emitted": emitted}


def _install(monkeypatch, queued, running, paused=False):
    monkeypatch.setitem(sys.modules, "db", FakeDB(queued, running))
    fake_switch = type("K", (), {"is_paused": staticmethod(lambda project=None: paused)})
    monkeypatch.setitem(sys.modules, "kill_switch", fake_switch)


def _run(times, state):
    for _ in range(times):
        sentinel.queue_stall_guard(state)


def test_the_incident_alarms(monkeypatch, wiring):
    """334 queued, 0 running -- the exact live shape."""
    _install(monkeypatch, queued=334, running=0)
    state = {}
    _run(3, state)
    assert any(kind == "queue-stall" for kind, _ in wiring["emitted"]), wiring["emitted"]
    action, detail = [x for x in wiring["logged"] if x[0] == "queue-stall"][0]
    assert "334 task(s) QUEUED and 0 RUNNING" in detail


def test_it_waits_for_several_passes_before_crying_wolf(monkeypatch, wiring):
    """A momentary gap between claims is not a stall."""
    _install(monkeypatch, queued=334, running=0)
    state = {}
    _run(2, state)
    assert wiring["emitted"] == []


def test_any_running_work_clears_the_counter(monkeypatch, wiring):
    _install(monkeypatch, queued=334, running=1)
    state = {}
    _run(10, state)
    assert wiring["emitted"] == []
    assert state["queue_stall_passes"] == 0


def test_a_run_after_a_stall_resets_it(monkeypatch, wiring):
    state = {}
    _install(monkeypatch, queued=334, running=0)
    _run(2, state)
    _install(monkeypatch, queued=334, running=2)
    _run(1, state)
    assert state["queue_stall_passes"] == 0
    _install(monkeypatch, queued=334, running=0)
    _run(2, state)
    assert wiring["emitted"] == [], "the counter did not actually reset"


def test_an_empty_queue_is_not_a_stall(monkeypatch, wiring):
    """An idle fleet with no work is idle, not broken."""
    _install(monkeypatch, queued=0, running=0)
    state = {}
    _run(10, state)
    assert wiring["emitted"] == []


def test_a_nearly_empty_queue_is_not_a_stall(monkeypatch, wiring):
    _install(monkeypatch, queued=4, running=0)
    state = {}
    _run(10, state)
    assert wiring["emitted"] == []


def test_a_paused_fleet_is_idle_on_purpose(monkeypatch, wiring):
    """Alarming on a deliberate pause trains the operator to ignore the alarm."""
    _install(monkeypatch, queued=334, running=0, paused=True)
    state = {}
    _run(10, state)
    assert wiring["emitted"] == []


def test_an_unreadable_kill_switch_does_not_silence_the_alarm(monkeypatch, wiring):
    _install(monkeypatch, queued=334, running=0)
    broken = type("K", (), {"is_paused": staticmethod(
        lambda project=None: (_ for _ in ()).throw(RuntimeError("no")))})
    monkeypatch.setitem(sys.modules, "kill_switch", broken)
    state = {}
    _run(3, state)
    assert any(kind == "queue-stall" for kind, _ in wiring["emitted"])


def test_an_unreadable_queue_does_not_raise(monkeypatch, wiring):
    class Broken:
        def select(self, *a, **kw):
            raise RuntimeError("database down")
    monkeypatch.setitem(sys.modules, "db", Broken())
    sentinel.queue_stall_guard({})
    assert any(action == "queue-stall-guard-error" for action, _ in wiring["logged"])


def test_the_cooldown_stops_a_repeat_alarm(monkeypatch, wiring):
    monkeypatch.setattr(sentinel, "QUEUE_STALL_COOLDOWN_S", 3600)
    _install(monkeypatch, queued=334, running=0)
    state = {}
    _run(8, state)
    assert len([k for k, _ in wiring["emitted"] if k == "queue-stall"]) == 1


def test_the_alarm_points_at_the_likely_cause(monkeypatch, wiring):
    """An alarm that does not say where to look costs the reader the same 39 minutes."""
    _install(monkeypatch, queued=334, running=0)
    _run(3, {})
    detail = [d for a, d in wiring["logged"] if a == "queue-stall"][0]
    assert "draining lanes" in detail
    assert "runner-start" in detail


def test_sentinel_actually_calls_it():
    """Structural: an unwired guard is a guard that never fires."""
    src = open(sentinel.__file__.replace(".pyc", ".py")).read()
    main_at = src.index("def main(")
    assert "queue_stall_guard(st)" in src[main_at:], "guard is defined but never called"
