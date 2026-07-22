#!/usr/bin/env python3
"""Tests for circuit_breaker.py."""
import sys, os, time, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import circuit_breaker
from circuit_breaker import CircuitBreaker, CLOSED, OPEN, HALF_OPEN


def test_starts_closed():
    cb = CircuitBreaker("t1")
    assert cb.state == CLOSED
    assert cb.allow() is True


def test_opens_after_threshold():
    cb = CircuitBreaker("t2", failure_threshold=3)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == OPEN
    assert cb.allow() is False


def test_half_open_after_cooldown():
    cb = CircuitBreaker("t3", failure_threshold=2, cooldown_s=0.1)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == OPEN
    time.sleep(0.15)
    assert cb.state == HALF_OPEN
    assert cb.allow() is True


def test_half_open_success_closes():
    cb = CircuitBreaker("t4", failure_threshold=2, cooldown_s=0.05)
    cb.record_failure()
    cb.record_failure()
    time.sleep(0.06)
    assert cb.allow() is True
    cb.record_success()
    cb.record_success()
    assert cb.state == CLOSED


def test_half_open_failure_reopens():
    cb = CircuitBreaker("t5", failure_threshold=2, cooldown_s=0.05)
    cb.record_failure()
    cb.record_failure()
    time.sleep(0.06)
    cb.allow()
    cb.record_failure()
    assert cb.state == OPEN


def test_reset():
    cb = CircuitBreaker("t6", failure_threshold=2)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == OPEN
    cb.reset()
    assert cb.state == CLOSED
    assert cb.allow() is True


def test_wrap_fallback():
    calls = []
    def good():
        calls.append(1)
        return 42
    def bad():
        calls.append(1)
        raise RuntimeError("boom")

    wrapped_good = circuit_breaker.wrap("t7_good", good, fallback=lambda: -1, failure_threshold=2)
    assert wrapped_good() == 42

    wrapped_bad = circuit_breaker.wrap("t7_bad", bad, fallback=lambda: -1, failure_threshold=2)
    assert wrapped_bad() == -1
    assert wrapped_bad() == -1
    # now open
    cb = circuit_breaker.get("t7_bad")
    assert cb.state == OPEN


def test_singleton_registry():
    cb1 = circuit_breaker.get("singleton_test", failure_threshold=3)
    cb2 = circuit_breaker.get("singleton_test")
    assert cb1 is cb2


def test_stats():
    cb = CircuitBreaker("t_stats", failure_threshold=3)
    cb.record_failure()
    s = cb.stats()
    assert s["name"] == "t_stats"
    assert s["state"] == CLOSED
    assert s["failure_count"] == 1


def test_thread_safety():
    cb = CircuitBreaker("t_thread", failure_threshold=100, cooldown_s=0.05)
    errors = []
    def hammer():
        try:
            for _ in range(50):
                cb.allow()
                cb.record_failure()
                cb.record_success()
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert cb.state in (CLOSED, OPEN, HALF_OPEN)


def test_half_open_limits_probes():
    cb = CircuitBreaker("t_probe_limit", failure_threshold=1, cooldown_s=0.05, half_open_max=1)
    cb.record_failure()
    time.sleep(0.06)
    assert cb.allow() is True   # first probe
    assert cb.allow() is False  # second blocked


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("All circuit_breaker tests passed")
