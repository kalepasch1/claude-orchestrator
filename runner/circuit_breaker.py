#!/usr/bin/env python3
"""circuit_breaker.py - Reusable circuit breaker for dependent-service calls.

States: CLOSED (normal) -> OPEN (failing, reject fast) -> HALF_OPEN (probe).
Thread-safe via threading.Lock.

Usage:
    cb = CircuitBreaker("supabase", failure_threshold=5, cooldown_s=60)
    if cb.allow():
        try:
            result = call_service()
            cb.record_success()
        except Exception:
            cb.record_failure()
    else:
        # fallback / degrade

Env vars:
    ORCH_CB_FAILURE_THRESHOLD   failures before opening (default: 5)
    ORCH_CB_COOLDOWN_S          seconds in OPEN before probing (default: 60)
    ORCH_CB_HALF_OPEN_MAX       max concurrent probes in HALF_OPEN (default: 1)
"""
import os
import threading
import time

FAILURE_THRESHOLD = int(os.environ.get("ORCH_CB_FAILURE_THRESHOLD", "5") or 5)
COOLDOWN_S = float(os.environ.get("ORCH_CB_COOLDOWN_S", "60") or 60)
HALF_OPEN_MAX = int(os.environ.get("ORCH_CB_HALF_OPEN_MAX", "1") or 1)

CLOSED, OPEN, HALF_OPEN = "CLOSED", "OPEN", "HALF_OPEN"

_registry_lock = threading.Lock()
_registry = {}


def get(name, **kwargs):
    """Module-level singleton: get or create a CircuitBreaker by name."""
    with _registry_lock:
        if name not in _registry:
            _registry[name] = CircuitBreaker(name, **kwargs)
        return _registry[name]


def reset_all():
    """Reset all registered breakers (testing)."""
    with _registry_lock:
        for cb in _registry.values():
            cb.reset()


class CircuitBreaker:
    """Thread-safe circuit breaker with CLOSED/OPEN/HALF_OPEN states."""

    def __init__(self, name, failure_threshold=None, cooldown_s=None,
                 half_open_max=None):
        self.name = name
        self.failure_threshold = failure_threshold or FAILURE_THRESHOLD
        self.cooldown_s = cooldown_s or COOLDOWN_S
        self.half_open_max = half_open_max or HALF_OPEN_MAX
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self._state = CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = 0.0
            self._half_open_in_flight = 0

    @property
    def state(self):
        with self._lock:
            return self._effective_state()

    def _effective_state(self):
        """Must be called under lock."""
        if self._state == OPEN:
            if time.time() - self._last_failure_time >= self.cooldown_s:
                return HALF_OPEN
        return self._state

    def allow(self):
        """Return True if the call should proceed, False to reject (degrade)."""
        with self._lock:
            s = self._effective_state()
            if s == CLOSED:
                return True
            if s == HALF_OPEN:
                if self._half_open_in_flight < self.half_open_max:
                    self._half_open_in_flight += 1
                    return True
                return False
            return False  # OPEN

    def record_success(self):
        with self._lock:
            s = self._effective_state()
            if s == HALF_OPEN:
                self._success_count += 1
                self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
                if self._success_count >= 2:
                    self._state = CLOSED
                    self._failure_count = 0
                    self._success_count = 0
            elif s == CLOSED:
                self._failure_count = 0

    def record_failure(self):
        with self._lock:
            s = self._effective_state()
            self._last_failure_time = time.time()
            if s == HALF_OPEN:
                self._state = OPEN
                self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
                self._success_count = 0
            elif s == CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._state = OPEN
                    self._success_count = 0

    def stats(self):
        with self._lock:
            return {
                "name": self.name,
                "state": self._effective_state(),
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "last_failure_time": self._last_failure_time,
            }


def wrap(name, fn, fallback=None, **cb_kwargs):
    """Convenience: wrap a callable with a circuit breaker.
    Returns fallback value (default None) when circuit is open."""
    cb = get(name, **cb_kwargs)
    def _wrapped(*args, **kwargs):
        if not cb.allow():
            return fallback() if callable(fallback) else fallback
        try:
            result = fn(*args, **kwargs)
            cb.record_success()
            return result
        except Exception:
            cb.record_failure()
            if callable(fallback):
                return fallback()
            return fallback
    return _wrapped
