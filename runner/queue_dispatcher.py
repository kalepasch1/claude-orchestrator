#!/usr/bin/env python3
"""
queue_dispatcher.py - Async task enqueue wrapper.

Thread-safe in-process FIFO queue that wraps synchronous task processing.
Callers use the module-level functions; the backing _QueueStore singleton
manages serialization, TTL eviction, and in-progress tracking.

The synchronous task processor (runner.py / db.py) is untouched; this
module is plumbing only.

Configuration (env vars):
    ORCH_QUEUE_PENDING_TTL    seconds a QUEUED entry lives before eviction (default: 3600)
    ORCH_QUEUE_PROC_TTL       seconds an IN-PROGRESS entry lives before eviction (default: 7200)
"""
import json
import os
import threading
import time

_PENDING_TTL = float(os.environ.get("ORCH_QUEUE_PENDING_TTL", "3600") or 3600)
_PROCESSING_TTL = float(os.environ.get("ORCH_QUEUE_PROC_TTL", "7200") or 7200)


class _QueueStore:
    """Backing store for queue_dispatcher. Inject _time_fn in tests to control TTL."""

    def __init__(self, pending_ttl=_PENDING_TTL, processing_ttl=_PROCESSING_TTL,
                 _time_fn=None):
        self._lock = threading.Lock()
        self._order = []         # list[str]: task_ids in FIFO insertion order
        self._data = {}          # task_id -> {"payload": str, "enqueued_at": float}
        self._in_progress = {}   # task_id -> {"payload": str, "started_at": float}
        self._pending_ttl = pending_ttl
        self._processing_ttl = processing_ttl
        self._time = _time_fn or time.monotonic

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, task_id, task_data):
        """Serialize task_data and push task_id onto the pending queue.

        Returns True on success, False if task_id already exists (pending or
        in-progress) or if task_data cannot be serialized.
        """
        try:
            payload = json.dumps(task_data, allow_nan=False)
        except (TypeError, ValueError):
            return False
        task_id = str(task_id)
        with self._lock:
            if task_id in self._data or task_id in self._in_progress:
                return False
            self._data[task_id] = {"payload": payload, "enqueued_at": self._time()}
            self._order.append(task_id)
        return True

    def dequeue(self):
        """Atomically pop the oldest non-stale pending task.

        Returns (task_id, task_data) on success, or (None, None) when the
        queue is empty or all remaining entries have expired.
        """
        with self._lock:
            self._evict_stale_pending()
            while self._order:
                task_id = self._order.pop(0)
                entry = self._data.pop(task_id, None)
                if entry is None:
                    continue
                try:
                    task_data = json.loads(entry["payload"])
                except (ValueError, KeyError):
                    task_data = None
                return task_id, task_data
        return None, None

    def mark_in_progress(self, task_id, task_data):
        """Record task_id as in-progress and (re-)set its processing TTL.

        task_data is re-serialized so callers can pass the same object returned
        by dequeue() without an extra copy.
        """
        task_id = str(task_id)
        try:
            payload = json.dumps(task_data, allow_nan=False)
        except (TypeError, ValueError):
            payload = "null"
        with self._lock:
            self._in_progress[task_id] = {
                "payload": payload,
                "started_at": self._time(),
            }

    def mark_done(self, task_id):
        """Remove task_id from in-progress tracking (success or failure)."""
        task_id = str(task_id)
        with self._lock:
            self._in_progress.pop(task_id, None)

    # ------------------------------------------------------------------
    # Introspection helpers (useful for operators and tests)
    # ------------------------------------------------------------------

    def pending_count(self):
        with self._lock:
            self._evict_stale_pending()
            return len(self._order)

    def in_progress_ids(self):
        with self._lock:
            self._evict_stale_processing()
            return list(self._in_progress.keys())

    def stats(self):
        with self._lock:
            self._evict_stale_pending()
            self._evict_stale_processing()
            return {
                "pending": len(self._order),
                "in_progress": len(self._in_progress),
            }

    def invalidate(self):
        """Clear all state; useful for tests and operator emergency resets."""
        with self._lock:
            self._order.clear()
            self._data.clear()
            self._in_progress.clear()

    # ------------------------------------------------------------------
    # Internal helpers (must be called with self._lock held)
    # ------------------------------------------------------------------

    def _evict_stale_pending(self):
        now = self._time()
        stale = [tid for tid, v in self._data.items()
                 if now - v["enqueued_at"] > self._pending_ttl]
        for tid in stale:
            self._data.pop(tid, None)
            try:
                self._order.remove(tid)
            except ValueError:
                pass

    def _evict_stale_processing(self):
        now = self._time()
        stale = [tid for tid, v in self._in_progress.items()
                 if now - v["started_at"] > self._processing_ttl]
        for tid in stale:
            self._in_progress.pop(tid, None)


# Module-level singleton — mirrors the pattern in warm_pool.py and resource_governor.py
_store = _QueueStore()


def enqueue(task_id, task_data):
    """Push task_id onto the async queue with serialized task_data.

    Returns True on success, False if already queued/in-progress or unserializable.
    """
    return _store.enqueue(task_id, task_data)


def dequeue():
    """Pop the oldest pending task.

    Returns (task_id, task_data) or (None, None) on empty / all-expired queue.
    """
    return _store.dequeue()


def mark_in_progress(task_id, task_data):
    """Register task_id as actively processing."""
    _store.mark_in_progress(task_id, task_data)


def mark_done(task_id):
    """Remove task_id from in-progress tracking."""
    _store.mark_done(task_id)


def pending_count():
    return _store.pending_count()


def in_progress_ids():
    return _store.in_progress_ids()


def stats():
    return _store.stats()


def invalidate():
    """Reset all queue state (tests, emergency operator use)."""
    _store.invalidate()
