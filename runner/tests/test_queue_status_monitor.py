"""Tests for queue_status_monitor."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from queue_status_monitor import QueueStatusMonitor, QueueEvent

def test_initial_state():
    m = QueueStatusMonitor()
    assert m.get_current() is None
    assert m.event_count == 0

def test_first_snapshot_no_events():
    m = QueueStatusMonitor()
    m.update_snapshot({"QUEUED": 5, "RUNNING": 2})
    assert m.event_count == 0  # No prior to compare

def test_change_emits_event():
    m = QueueStatusMonitor()
    m.update_snapshot({"QUEUED": 5, "RUNNING": 2})
    m.update_snapshot({"QUEUED": 3, "RUNNING": 4})
    assert m.event_count >= 1

def test_callback_called():
    events = []
    m = QueueStatusMonitor()
    m.on_change(lambda e: events.append(e))
    m.update_snapshot({"QUEUED": 5})
    m.update_snapshot({"QUEUED": 3})
    assert len(events) >= 1

def test_no_change_no_event():
    m = QueueStatusMonitor()
    m.update_snapshot({"QUEUED": 5})
    m.update_snapshot({"QUEUED": 5})
    assert m.event_count == 0

def test_history_limit():
    m = QueueStatusMonitor()
    m.update_snapshot({"QUEUED": 0})
    for i in range(6000):
        m.update_snapshot({"QUEUED": i + 1})
    assert m.event_count <= 5001

def test_get_status_history():
    m = QueueStatusMonitor()
    m.update_snapshot({"QUEUED": 5})
    m.update_snapshot({"QUEUED": 3})
    h = m.get_status_history(limit=1)
    assert len(h) == 1
    assert "type" in h[0]

def test_get_current():
    m = QueueStatusMonitor()
    m.update_snapshot({"QUEUED": 5, "RUNNING": 2})
    c = m.get_current()
    assert c == {"QUEUED": 5, "RUNNING": 2}

def test_event_to_dict():
    e = QueueEvent("state_change", "c1", {"state": "QUEUED"})
    d = e.to_dict()
    assert d["type"] == "state_change"
    assert "timestamp" in d

def test_callback_error_handled():
    m = QueueStatusMonitor()
    m.on_change(lambda e: 1/0)  # Will raise
    m.update_snapshot({"QUEUED": 5})
    m.update_snapshot({"QUEUED": 3})
    # Should not crash
    assert m.event_count >= 1

def test_concurrent_state_tracking():
    m = QueueStatusMonitor()
    m.update_snapshot({"QUEUED": 10, "RUNNING": 5, "DONE": 100})
    m.update_snapshot({"QUEUED": 8, "RUNNING": 7, "DONE": 100})
    assert m.event_count == 2  # QUEUED and RUNNING changed, DONE didn't
