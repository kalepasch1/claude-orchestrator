"""Real-time queue status: every change is emitted, including a state that vanishes.

`update_snapshot` iterated only the CURRENT snapshot's keys, so a state that disappeared
— the queue drains and the producer stops emitting the key — produced no event at all,
and a dashboard subscribed to those events kept showing the last non-zero count forever.
Silence is indistinguishable from "unchanged" on a live feed, which is the one thing a
real-time status surface must never do.
"""
import os
import sys

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

from queue_status_monitor import QueueEvent, QueueStatusMonitor  # noqa: E402


def _events(monitor):
    return [e["data"] for e in monitor.get_status_history()]


def test_first_snapshot_emits_nothing():
    m = QueueStatusMonitor()
    m.update_snapshot({"QUEUED": 5})
    assert m.event_count == 0, "there is no prior state to have changed from"
    assert m.get_current() == {"QUEUED": 5}


def test_change_emits_with_prev_current_and_delta():
    m = QueueStatusMonitor()
    m.update_snapshot({"QUEUED": 5})
    m.update_snapshot({"QUEUED": 8}, change_id="c1")
    assert _events(m) == [{"state": "QUEUED", "prev": 5, "current": 8, "delta": 3}]
    assert m.get_status_history()[0]["change_id"] == "c1"


def test_unchanged_state_emits_nothing():
    m = QueueStatusMonitor()
    m.update_snapshot({"QUEUED": 5})
    m.update_snapshot({"QUEUED": 5})
    assert m.event_count == 0


def test_vanished_state_is_reported_as_a_drop_to_zero():
    """The regression: QUEUED disappears from the snapshot entirely."""
    m = QueueStatusMonitor()
    m.update_snapshot({"QUEUED": 40, "RUNNING": 2})
    m.update_snapshot({"RUNNING": 2})
    assert _events(m) == [{"state": "QUEUED", "prev": 40, "current": 0, "delta": -40}]


def test_new_state_appearing_is_emitted():
    m = QueueStatusMonitor()
    m.update_snapshot({"QUEUED": 1})
    m.update_snapshot({"QUEUED": 1, "CONFLICT": 3})
    assert _events(m) == [{"state": "CONFLICT", "prev": 0, "current": 3, "delta": 3}]


def test_empty_snapshot_drains_every_state():
    m = QueueStatusMonitor()
    m.update_snapshot({"QUEUED": 4, "RUNNING": 1})
    m.update_snapshot({})
    assert sorted(e["state"] for e in _events(m)) == ["QUEUED", "RUNNING"]
    assert all(e["current"] == 0 for e in _events(m))


def test_none_snapshot_is_treated_as_empty_not_a_crash():
    m = QueueStatusMonitor()
    m.update_snapshot({"QUEUED": 2})
    m.update_snapshot(None)
    assert m.get_current() is None or m.get_current() == {}


def test_callback_receives_events_and_a_broken_one_is_isolated():
    m = QueueStatusMonitor()
    seen = []
    m.on_change(lambda e: (_ for _ in ()).throw(RuntimeError("subscriber down")))
    m.on_change(seen.append)
    m.update_snapshot({"QUEUED": 1})
    m.update_snapshot({"QUEUED": 2})
    assert len(seen) == 1, "one bad subscriber must not starve the others"
    assert isinstance(seen[0], QueueEvent)


def test_dashboard_before_any_snapshot_is_well_formed():
    d = QueueStatusMonitor().dashboard()
    assert d["states"] == {} and d["total"] == 0
    assert d["moving"] is False and d["primed"] is False
    assert d["recent_events"] == []


def test_dashboard_reports_totals_and_movement():
    m = QueueStatusMonitor()
    m.update_snapshot({"QUEUED": 10, "RUNNING": 0})
    m.update_snapshot({"QUEUED": 7, "RUNNING": 3})
    d = m.dashboard()
    assert d["states"] == {"QUEUED": 7, "RUNNING": 3}
    assert d["total"] == 10
    assert d["deltas"] == {"QUEUED": -3, "RUNNING": 3}
    assert d["moving"] is True
    assert d["primed"] is True


def test_dashboard_reports_a_frozen_queue_as_not_moving():
    m = QueueStatusMonitor()
    m.update_snapshot({"QUEUED": 42})
    m.update_snapshot({"QUEUED": 42})
    d = m.dashboard()
    assert d["moving"] is False
    assert d["states"] == {"QUEUED": 42}


def test_history_is_bounded():
    m = QueueStatusMonitor()
    for i in range(6000):
        m.update_snapshot({"QUEUED": i})
    assert m.event_count <= 5000, "unbounded history would grow without limit"
