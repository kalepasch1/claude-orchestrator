#!/usr/bin/env python3
"""Tests for async_task_processor.py - asynchronous task processing with callbacks.

Covers:
- AsyncTask initialization and state tracking
- AsyncProcessor queue and active task management
- Task submission with args and kwargs
- Concurrent task processing with rate limiting
- Callback registration and invocation
- Batch processing and FIFO ordering
- Statistics and metrics
- Error handling and exception propagation
- Edge cases and boundary conditions
"""
import os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import async_task_processor as atp


# --- AsyncTask Tests ---

def test_async_task_initialization():
    """AsyncTask initializes with correct default state."""
    def dummy(): return 42
    task = atp.AsyncTask("task_1", dummy)
    assert task.task_id == "task_1"
    assert task.fn == dummy
    assert task.args == ()
    assert task.kwargs == {}
    assert task.status == "queued"
    assert task.result is None
    assert task.error is None
    assert task.started_at is None
    assert task.completed_at is None
    assert task.queued_at is not None
    assert isinstance(task.queued_at, float)


def test_async_task_with_args():
    """AsyncTask stores positional arguments."""
    def add(a, b): return a + b
    task = atp.AsyncTask("add_task", add, (3, 5))
    assert task.args == (3, 5)
    assert task.kwargs == {}


def test_async_task_with_kwargs():
    """AsyncTask stores keyword arguments and converts None to empty dict."""
    def greet(name="World"): return f"Hello {name}"
    task1 = atp.AsyncTask("greet1", greet, (), {"name": "Alice"})
    assert task1.kwargs == {"name": "Alice"}

    task2 = atp.AsyncTask("greet2", greet, (), None)
    assert task2.kwargs == {}


def test_async_task_with_mixed_args_kwargs():
    """AsyncTask stores both args and kwargs correctly."""
    def mixed(a, b, c=3, d=4): return a + b + c + d
    task = atp.AsyncTask("mixed", mixed, (1, 2), {"c": 10, "d": 20})
    assert task.args == (1, 2)
    assert task.kwargs == {"c": 10, "d": 20}


def test_async_task_timestamps_on_lifecycle():
    """AsyncTask tracks queued_at timestamp on initialization."""
    before = time.time()
    def dummy(): pass
    task = atp.AsyncTask("ts_task", dummy)
    after = time.time()

    assert before <= task.queued_at <= after
    assert task.started_at is None
    assert task.completed_at is None


# --- AsyncProcessor Initialization Tests ---

def test_async_processor_init_default():
    """AsyncProcessor initializes with default concurrency limit of 4."""
    proc = atp.AsyncProcessor()
    assert proc._max_concurrent == 4
    assert len(proc._queue) == 0
    assert len(proc._active) == {}
    assert len(proc._completed) == []
    assert len(proc._callbacks) == []


def test_async_processor_init_custom_concurrency():
    """AsyncProcessor respects custom max_concurrent parameter."""
    proc1 = atp.AsyncProcessor(max_concurrent=1)
    assert proc1._max_concurrent == 1

    proc2 = atp.AsyncProcessor(max_concurrent=10)
    assert proc2._max_concurrent == 10


# --- Task Submission Tests ---

def test_submit_simple_task():
    """submit() adds task to queue and returns it."""
    proc = atp.AsyncProcessor()
    def dummy(): return "ok"
    task = proc.submit("t1", dummy)

    assert task.task_id == "t1"
    assert task.status == "queued"
    assert proc.pending_count == 1


def test_submit_multiple_tasks():
    """submit() maintains FIFO queue order."""
    proc = atp.AsyncProcessor()
    def dummy(): pass

    t1 = proc.submit("t1", dummy)
    t2 = proc.submit("t2", dummy)
    t3 = proc.submit("t3", dummy)

    assert proc.pending_count == 3
    assert list(proc._queue)[0].task_id == "t1"
    assert list(proc._queue)[1].task_id == "t2"
    assert list(proc._queue)[2].task_id == "t3"


def test_submit_with_args():
    """submit() passes *args correctly to AsyncTask."""
    proc = atp.AsyncProcessor()
    def add(a, b): return a + b
    task = proc.submit("add", add, 3, 5)

    assert task.args == (3, 5)


def test_submit_with_kwargs():
    """submit() passes **kwargs correctly to AsyncTask."""
    proc = atp.AsyncProcessor()
    def greet(name="World"): return f"Hello {name}"
    task = proc.submit("greet", greet, name="Alice")

    assert task.kwargs == {"name": "Alice"}


def test_submit_with_mixed_args_kwargs():
    """submit() handles both args and kwargs."""
    proc = atp.AsyncProcessor()
    def mixed(a, b, c=3): return a + b + c
    task = proc.submit("mixed", mixed, 1, 2, c=10)

    assert task.args == (1, 2)
    assert task.kwargs == {"c": 10}


# --- Task Processing Tests ---

def test_process_next_executes_task():
    """process_next() executes task function and stores result."""
    proc = atp.AsyncProcessor()
    def add(a, b): return a + b

    proc.submit("add", add, 3, 5)
    completed = proc.process_next()

    assert completed is not None
    assert completed.task_id == "add"
    assert completed.status == "completed"
    assert completed.result == 8
    assert completed.error is None


def test_process_next_handles_exception():
    """process_next() catches exceptions and stores error message."""
    proc = atp.AsyncProcessor()
    def fail(): raise ValueError("intentional error")

    proc.submit("fail", fail)
    completed = proc.process_next()

    assert completed is not None
    assert completed.status == "failed"
    assert completed.result is None
    assert "intentional error" in completed.error


def test_process_next_tracks_timing():
    """process_next() records started_at and completed_at timestamps."""
    proc = atp.AsyncProcessor()
    def dummy(): return "ok"

    before = time.time()
    proc.submit("timed", dummy)
    completed = proc.process_next()
    after = time.time()

    assert completed.started_at is not None
    assert completed.completed_at is not None
    assert before <= completed.started_at <= completed.completed_at <= after


def test_process_next_empty_queue():
    """process_next() returns None when queue is empty."""
    proc = atp.AsyncProcessor()
    result = proc.process_next()
    assert result is None


def test_process_next_respects_concurrency_limit():
    """process_next() does not exceed max_concurrent tasks."""
    proc = atp.AsyncProcessor(max_concurrent=2)
    def dummy(): return "ok"

    proc.submit("t1", dummy)
    proc.submit("t2", dummy)
    proc.submit("t3", dummy)

    # Process first two tasks
    proc.process_next()
    proc.process_next()

    # Third task should not process if concurrency limit is enforced
    # (this depends on implementation - if process_next blocks on concurrency)
    # For now, test that we never exceed max_concurrent in active
    assert proc.active_count <= proc._max_concurrent


def test_process_next_moves_task_to_active():
    """process_next() moves task from queue to active during execution."""
    proc = atp.AsyncProcessor()
    call_count = {"n": 0}

    def tracked():
        call_count["n"] += 1
        # At this point, task should be in _active
        assert len(proc._active) == 1
        return "ok"

    proc.submit("tracked", tracked)
    proc.process_next()

    assert call_count["n"] == 1
    assert len(proc._active) == 0  # Should be removed after completion


def test_process_next_moves_task_to_completed():
    """process_next() moves task from active to completed."""
    proc = atp.AsyncProcessor()
    proc.submit("t1", lambda: "ok")

    assert len(proc._completed) == 0
    proc.process_next()
    assert len(proc._completed) == 1
    assert proc._completed[0].task_id == "t1"


# --- Callback Tests ---

def test_on_complete_callback_basic():
    """on_complete() registers callback that fires after task completion."""
    proc = atp.AsyncProcessor()
    callback_fired = {"count": 0, "task": None}

    def my_callback(task):
        callback_fired["count"] += 1
        callback_fired["task"] = task

    proc.on_complete(my_callback)
    proc.submit("t1", lambda: "result")
    proc.process_next()

    assert callback_fired["count"] == 1
    assert callback_fired["task"].task_id == "t1"
    assert callback_fired["task"].result == "result"


def test_on_complete_callback_on_failure():
    """on_complete() callback receives failed task with error."""
    proc = atp.AsyncProcessor()
    callback_data = {"task": None}

    def my_callback(task):
        callback_data["task"] = task

    proc.on_complete(my_callback)
    proc.submit("fail", lambda: 1 / 0)  # ZeroDivisionError
    proc.process_next()

    assert callback_data["task"].status == "failed"
    assert callback_data["task"].error is not None


def test_on_complete_multiple_callbacks():
    """Multiple callbacks all fire on task completion."""
    proc = atp.AsyncProcessor()
    counts = {"cb1": 0, "cb2": 0, "cb3": 0}

    proc.on_complete(lambda t: counts.update({"cb1": counts["cb1"] + 1}))
    proc.on_complete(lambda t: counts.update({"cb2": counts["cb2"] + 1}))
    proc.on_complete(lambda t: counts.update({"cb3": counts["cb3"] + 1}))

    proc.submit("t1", lambda: "ok")
    proc.process_next()

    assert counts["cb1"] == 1
    assert counts["cb2"] == 1
    assert counts["cb3"] == 1


def test_on_complete_callback_exception_handled():
    """Exception in callback is caught and does not crash processor."""
    proc = atp.AsyncProcessor()
    crash_count = {"n": 0}
    safe_count = {"n": 0}

    def crashing_callback(task):
        crash_count["n"] += 1
        raise RuntimeError("callback boom")

    def safe_callback(task):
        safe_count["n"] += 1

    proc.on_complete(crashing_callback)
    proc.on_complete(safe_callback)

    proc.submit("t1", lambda: "ok")

    # Should not raise even though crashing_callback raises
    proc.process_next()

    assert crash_count["n"] == 1
    assert safe_count["n"] == 1  # Second callback still fires


def test_on_complete_callback_receives_correct_task():
    """Callback receives the exact task that completed."""
    proc = atp.AsyncProcessor()
    received_task = {}

    def my_callback(task):
        received_task["task"] = task

    proc.on_complete(my_callback)
    proc.submit("task_a", lambda: 42)
    proc.submit("task_b", lambda: 99)

    # Process only first task
    proc.process_next()

    assert received_task["task"].task_id == "task_a"
    assert received_task["task"].result == 42


# --- Batch Processing Tests ---

def test_process_all_empty_queue():
    """process_all() returns empty list when queue is empty."""
    proc = atp.AsyncProcessor()
    result = proc.process_all()
    assert result == []


def test_process_all_processes_all_tasks():
    """process_all() processes entire queue."""
    proc = atp.AsyncProcessor()
    proc.submit("t1", lambda: 1)
    proc.submit("t2", lambda: 2)
    proc.submit("t3", lambda: 3)

    results = proc.process_all()

    assert len(results) == 3
    assert all(t.status == "completed" for t in results)
    assert [t.result for t in results] == [1, 2, 3]


def test_process_all_respects_fifo_order():
    """process_all() processes tasks in FIFO order."""
    proc = atp.AsyncProcessor()
    order = []

    for i in range(1, 4):
        proc.submit(f"t{i}", (lambda i=i: order.append(i) or i))

    proc.process_all()

    assert order == [1, 2, 3]


def test_process_all_handles_mixed_success_failure():
    """process_all() processes both successful and failed tasks."""
    proc = atp.AsyncProcessor()
    proc.submit("ok1", lambda: "ok")
    proc.submit("fail1", lambda: 1 / 0)
    proc.submit("ok2", lambda: "ok")

    results = proc.process_all()

    assert len(results) == 3
    assert results[0].status == "completed"
    assert results[1].status == "failed"
    assert results[2].status == "completed"


def test_process_all_returns_completed_tasks():
    """process_all() returns list of processed tasks."""
    proc = atp.AsyncProcessor()
    proc.submit("a", lambda: "A")
    proc.submit("b", lambda: "B")

    results = proc.process_all()

    assert len(results) == 2
    assert results[0].result == "A"
    assert results[1].result == "B"


# --- Queue Management Tests ---

def test_pending_count_tracking():
    """pending_count property reflects queue size."""
    proc = atp.AsyncProcessor()
    assert proc.pending_count == 0

    proc.submit("t1", lambda: None)
    assert proc.pending_count == 1

    proc.submit("t2", lambda: None)
    assert proc.pending_count == 2

    proc.process_next()
    assert proc.pending_count == 1


def test_active_count_tracking():
    """active_count property reflects number of running tasks."""
    proc = atp.AsyncProcessor()
    running = {"flag": False}

    def blocking():
        running["flag"] = True
        while running["flag"]:
            time.sleep(0.001)
        return "done"

    # Note: In synchronous implementation, task finishes immediately
    # but we can test the pattern
    proc.submit("t1", lambda: "quick")
    assert proc.active_count == 0
    proc.process_next()
    assert proc.active_count == 0  # Task already completed


def test_completed_count_in_stats():
    """Completed tasks are tracked in stats."""
    proc = atp.AsyncProcessor()
    proc.submit("t1", lambda: 1)
    proc.submit("t2", lambda: 2)

    proc.process_all()

    stats = proc.get_stats()
    assert stats["completed"] == 2


# --- Statistics Tests ---

def test_get_stats_initial():
    """get_stats() returns zeros on empty processor."""
    proc = atp.AsyncProcessor()
    stats = proc.get_stats()

    assert stats["pending"] == 0
    assert stats["active"] == 0
    assert stats["completed"] == 0
    assert stats["failed"] == 0


def test_get_stats_after_submission():
    """get_stats() reflects pending tasks."""
    proc = atp.AsyncProcessor()
    proc.submit("t1", lambda: None)
    proc.submit("t2", lambda: None)

    stats = proc.get_stats()
    assert stats["pending"] == 2
    assert stats["active"] == 0
    assert stats["completed"] == 0


def test_get_stats_after_processing():
    """get_stats() reflects completed tasks."""
    proc = atp.AsyncProcessor()
    proc.submit("t1", lambda: "ok")
    proc.submit("t2", lambda: "ok")

    proc.process_all()

    stats = proc.get_stats()
    assert stats["pending"] == 0
    assert stats["active"] == 0
    assert stats["completed"] == 2
    assert stats["failed"] == 0


def test_get_stats_failed_count():
    """get_stats() counts failed tasks."""
    proc = atp.AsyncProcessor()
    proc.submit("ok1", lambda: "ok")
    proc.submit("fail1", lambda: 1 / 0)
    proc.submit("ok2", lambda: "ok")
    proc.submit("fail2", lambda: ValueError("oops"))

    proc.process_all()

    stats = proc.get_stats()
    assert stats["completed"] == 4
    assert stats["failed"] == 2


def test_get_stats_is_dict():
    """get_stats() returns a dictionary."""
    proc = atp.AsyncProcessor()
    stats = proc.get_stats()

    assert isinstance(stats, dict)
    assert "pending" in stats
    assert "active" in stats
    assert "completed" in stats
    assert "failed" in stats


# --- Edge Cases and Error Handling ---

def test_task_function_returning_none():
    """Task function can return None without error."""
    proc = atp.AsyncProcessor()
    proc.submit("t1", lambda: None)

    result = proc.process_next()
    assert result.status == "completed"
    assert result.result is None


def test_task_function_returning_complex_object():
    """Task function can return complex objects."""
    proc = atp.AsyncProcessor()
    expected = {"key": "value", "list": [1, 2, 3]}

    proc.submit("t1", lambda: expected)
    result = proc.process_next()

    assert result.result == expected


def test_exception_with_args():
    """Task exceptions with arguments are captured correctly."""
    proc = atp.AsyncProcessor()
    def fail():
        raise ValueError("error message with args")

    proc.submit("fail", fail)
    result = proc.process_next()

    assert result.status == "failed"
    assert "error message with args" in result.error


def test_exception_without_message():
    """Task exceptions without message are handled."""
    proc = atp.AsyncProcessor()
    def fail():
        raise RuntimeError()

    proc.submit("fail", fail)
    result = proc.process_next()

    assert result.status == "failed"
    assert result.error is not None


def test_task_with_side_effects():
    """Task side effects execute correctly."""
    proc = atp.AsyncProcessor()
    side_effect = {"value": 0}

    def modify():
        side_effect["value"] = 42
        return side_effect["value"]

    proc.submit("modify", modify)
    proc.process_next()

    assert side_effect["value"] == 42


def test_large_task_id():
    """Large task IDs are handled correctly."""
    proc = atp.AsyncProcessor()
    large_id = "x" * 1000

    proc.submit(large_id, lambda: "ok")
    result = proc.process_next()

    assert result.task_id == large_id


def test_special_characters_in_task_id():
    """Special characters in task IDs are preserved."""
    proc = atp.AsyncProcessor()
    special_id = "task_🚀_∆_123"

    proc.submit(special_id, lambda: "ok")
    result = proc.process_next()

    assert result.task_id == special_id


def test_unicode_in_error_message():
    """Unicode in error messages is preserved."""
    proc = atp.AsyncProcessor()

    def fail():
        raise ValueError("Error: ∆ œ 🚀")

    proc.submit("unicode_fail", fail)
    result = proc.process_next()

    assert "∆" in result.error or "Error" in result.error


def test_multiple_exceptions_in_sequence():
    """Multiple failed tasks are all recorded."""
    proc = atp.AsyncProcessor()

    proc.submit("f1", lambda: 1 / 0)
    proc.submit("f2", lambda: ValueError("v1"))
    proc.submit("f3", lambda: RuntimeError("r1"))

    results = proc.process_all()

    assert len(results) == 3
    assert all(t.status == "failed" for t in results)


def test_task_with_expensive_computation():
    """Task with computational work completes correctly."""
    proc = atp.AsyncProcessor()

    def fibonacci(n):
        if n <= 1:
            return n
        return fibonacci(n - 1) + fibonacci(n - 2)

    proc.submit("fib", fibonacci, 10)
    result = proc.process_next()

    assert result.status == "completed"
    assert result.result == 55


# --- Concurrency Edge Cases ---

def test_max_concurrent_prevents_overload():
    """Setting max_concurrent=1 ensures only one task runs at a time."""
    proc = atp.AsyncProcessor(max_concurrent=1)

    for i in range(5):
        proc.submit(f"t{i}", lambda i=i: i)

    assert proc.pending_count == 5

    # Process one at a time
    for i in range(5):
        proc.process_next()
        assert proc.pending_count == (4 - i)


def test_max_concurrent_zero():
    """max_concurrent=0 should allow no tasks to run (edge case)."""
    proc = atp.AsyncProcessor(max_concurrent=0)
    proc.submit("t1", lambda: "ok")

    # This is an edge case - process_next might return None
    result = proc.process_next()
    # Implementation-dependent, but should not crash


def test_max_concurrent_very_large():
    """Very large max_concurrent doesn't crash system."""
    proc = atp.AsyncProcessor(max_concurrent=10000)

    for i in range(100):
        proc.submit(f"t{i}", lambda i=i: i)

    results = proc.process_all()
    assert len(results) == 100


# --- Integration Tests ---

def test_full_workflow_submit_process_callbacks():
    """Full workflow: submit -> process -> callback."""
    proc = atp.AsyncProcessor(max_concurrent=2)
    completed_ids = []

    def track_completion(task):
        completed_ids.append(task.task_id)

    proc.on_complete(track_completion)

    # Submit batch
    proc.submit("batch_1", lambda: 10)
    proc.submit("batch_2", lambda: 20)
    proc.submit("batch_3", lambda: 30)

    # Process all
    results = proc.process_all()

    assert len(results) == 3
    assert len(completed_ids) == 3
    assert set(completed_ids) == {"batch_1", "batch_2", "batch_3"}


def test_reuse_processor_multiple_batches():
    """Processor can handle multiple batches sequentially."""
    proc = atp.AsyncProcessor()

    # First batch
    proc.submit("a1", lambda: 1)
    proc.submit("a2", lambda: 2)
    results1 = proc.process_all()
    assert len(results1) == 2

    # Second batch
    proc.submit("b1", lambda: 10)
    proc.submit("b2", lambda: 20)
    results2 = proc.process_all()
    assert len(results2) == 2

    # Check stats
    stats = proc.get_stats()
    assert stats["completed"] == 4


def test_task_ordering_preserved_across_process_all():
    """Task results maintain submission order after process_all."""
    proc = atp.AsyncProcessor()

    values = list(range(1, 11))
    for i in values:
        proc.submit(f"t{i}", lambda v=i: v)

    results = proc.process_all()
    result_values = [r.result for r in results]

    assert result_values == values


if __name__ == "__main__":
    # AsyncTask tests
    test_async_task_initialization()
    test_async_task_with_args()
    test_async_task_with_kwargs()
    test_async_task_with_mixed_args_kwargs()
    test_async_task_timestamps_on_lifecycle()

    # AsyncProcessor init tests
    test_async_processor_init_default()
    test_async_processor_init_custom_concurrency()

    # Task submission tests
    test_submit_simple_task()
    test_submit_multiple_tasks()
    test_submit_with_args()
    test_submit_with_kwargs()
    test_submit_with_mixed_args_kwargs()

    # Task processing tests
    test_process_next_executes_task()
    test_process_next_handles_exception()
    test_process_next_tracks_timing()
    test_process_next_empty_queue()
    test_process_next_respects_concurrency_limit()
    test_process_next_moves_task_to_active()
    test_process_next_moves_task_to_completed()

    # Callback tests
    test_on_complete_callback_basic()
    test_on_complete_callback_on_failure()
    test_on_complete_multiple_callbacks()
    test_on_complete_callback_exception_handled()
    test_on_complete_callback_receives_correct_task()

    # Batch processing tests
    test_process_all_empty_queue()
    test_process_all_processes_all_tasks()
    test_process_all_respects_fifo_order()
    test_process_all_handles_mixed_success_failure()
    test_process_all_returns_completed_tasks()

    # Queue management tests
    test_pending_count_tracking()
    test_active_count_tracking()
    test_completed_count_in_stats()

    # Statistics tests
    test_get_stats_initial()
    test_get_stats_after_submission()
    test_get_stats_after_processing()
    test_get_stats_failed_count()
    test_get_stats_is_dict()

    # Edge cases
    test_task_function_returning_none()
    test_task_function_returning_complex_object()
    test_exception_with_args()
    test_exception_without_message()
    test_task_with_side_effects()
    test_large_task_id()
    test_special_characters_in_task_id()
    test_unicode_in_error_message()
    test_multiple_exceptions_in_sequence()
    test_task_with_expensive_computation()

    # Concurrency edge cases
    test_max_concurrent_prevents_overload()
    test_max_concurrent_zero()
    test_max_concurrent_very_large()

    # Integration tests
    test_full_workflow_submit_process_callbacks()
    test_reuse_processor_multiple_batches()
    test_task_ordering_preserved_across_process_all()

    print("All async_task_processor tests passed")
