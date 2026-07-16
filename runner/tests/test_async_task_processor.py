"""Tests for async_task_processor."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from async_task_processor import AsyncProcessor, AsyncTask

def test_submit():
    p = AsyncProcessor()
    t = p.submit("t1", lambda: "ok")
    assert t.status == "queued"
    assert p.pending_count == 1

def test_process_next():
    p = AsyncProcessor()
    p.submit("t1", lambda: "result")
    t = p.process_next()
    assert t.status == "completed"
    assert t.result == "result"

def test_process_failure():
    p = AsyncProcessor()
    p.submit("t1", lambda: 1/0)
    t = p.process_next()
    assert t.status == "failed"
    assert t.error is not None

def test_process_all():
    p = AsyncProcessor()
    for i in range(5):
        p.submit(f"t{i}", lambda x=i: x * 2)
    results = p.process_all()
    assert len(results) == 5

def test_callback():
    completed = []
    p = AsyncProcessor()
    p.on_complete(lambda t: completed.append(t.task_id))
    p.submit("t1", lambda: "ok")
    p.process_next()
    assert completed == ["t1"]

def test_max_concurrent():
    p = AsyncProcessor(max_concurrent=1)
    p.submit("t1", lambda: "a")
    p.submit("t2", lambda: "b")
    # Can only process one at a time (but in sync mode both complete)
    results = p.process_all()
    assert len(results) == 2

def test_stats():
    p = AsyncProcessor()
    p.submit("t1", lambda: "ok")
    p.submit("t2", lambda: 1/0)
    p.process_all()
    stats = p.get_stats()
    assert stats["completed"] == 2
    assert stats["failed"] == 1

def test_empty_queue():
    p = AsyncProcessor()
    assert p.process_next() is None

def test_task_timing():
    p = AsyncProcessor()
    p.submit("t1", lambda: "ok")
    t = p.process_next()
    assert t.started_at is not None
    assert t.completed_at is not None
    assert t.completed_at >= t.started_at

def test_task_with_args():
    p = AsyncProcessor()
    p.submit("t1", lambda a, b: a + b, 3, 4)
    t = p.process_next()
    assert t.result == 7
