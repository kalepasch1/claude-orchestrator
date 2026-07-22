"""
task_queue_interface.py — abstract task queue interface with pluggable backends.

Provides a backend-agnostic abstraction over task enqueueing and status
management. The default Supabase backend is a thin wrapper around the existing
db.py module; the Redis backend is available when redis-py is installed and
ORCH_REDIS_URL is set.

Backend selection: set ORCH_QUEUE_BACKEND env var to 'supabase' (default) or 'redis'.
"""
from __future__ import annotations

import abc
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TaskQueueInterface(abc.ABC):
    """Abstract queue — enqueue, claim, and status-track tasks."""

    @abc.abstractmethod
    def enqueue(self, task: dict) -> dict:
        """Insert a task into the queue; return the created row."""

    @abc.abstractmethod
    def dequeue(self, runner_id: str) -> "dict | None":
        """Atomically claim one QUEUED task for runner_id; return it or None."""

    @abc.abstractmethod
    def update_status(self, task_id: str, state: str, note: str = "") -> bool:
        """Transition task to state; return True on success."""

    @abc.abstractmethod
    def get_status(self, task_id: str) -> "str | None":
        """Return current state string for task_id, or None if unknown."""


class SupabaseTaskQueue(TaskQueueInterface):
    """Concrete queue backed by the existing Supabase/PostgREST db module."""

    def __init__(self):
        import db as _db
        self._db = _db

    def enqueue(self, task: dict) -> dict:
        return self._db.insert("tasks", task) or {}

    def dequeue(self, runner_id: str) -> "dict | None":
        return self._db.claim_task(runner_id)

    def update_status(self, task_id: str, state: str, note: str = "") -> bool:
        patch = {"state": state, "updated_at": "now()"}
        if note:
            patch["note"] = note
        try:
            self._db.update("tasks", {"id": task_id}, patch)
            return True
        except Exception:
            return False

    def get_status(self, task_id: str) -> "str | None":
        rows = self._db.select(
            "tasks",
            {"select": "state", "id": f"eq.{task_id}", "limit": "1"},
        ) or []
        return rows[0]["state"] if rows else None


class RedisTaskQueue(TaskQueueInterface):
    """Redis-backed queue — install redis-py and set ORCH_REDIS_URL to activate."""

    QUEUE_KEY_ENV = "ORCH_REDIS_QUEUE_KEY"
    STATUS_PREFIX_ENV = "ORCH_REDIS_STATUS_PREFIX"

    def __init__(self, url: "str | None" = None):
        try:
            import redis  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("redis-py not installed; pip install redis") from exc
        import json as _json
        self._json = _json
        self._r = redis.from_url(url or os.environ["ORCH_REDIS_URL"])
        self._queue_key = os.environ.get(self.QUEUE_KEY_ENV, "orch:tasks")
        self._status_prefix = os.environ.get(self.STATUS_PREFIX_ENV, "orch:status:")

    def enqueue(self, task: dict) -> dict:
        task_id = task.get("id") or task.get("slug") or ""
        self._r.lpush(self._queue_key, self._json.dumps(task))
        if task_id:
            self._r.set(f"{self._status_prefix}{task_id}", "QUEUED")
        return task

    def dequeue(self, runner_id: str) -> "dict | None":
        result = self._r.brpop(self._queue_key, timeout=0)
        if not result:
            return None
        _, payload = result
        task = self._json.loads(payload)
        task_id = task.get("id") or task.get("slug") or ""
        if task_id:
            self._r.set(f"{self._status_prefix}{task_id}", "RUNNING")
        return task

    def update_status(self, task_id: str, state: str, note: str = "") -> bool:
        try:
            self._r.set(f"{self._status_prefix}{task_id}", state)
            return True
        except Exception:
            return False

    def get_status(self, task_id: str) -> "str | None":
        val = self._r.get(f"{self._status_prefix}{task_id}")
        return val.decode() if val else None


_BACKENDS: dict = {
    "supabase": SupabaseTaskQueue,
    "redis": RedisTaskQueue,
}

_instance: "TaskQueueInterface | None" = None


def get_queue() -> TaskQueueInterface:
    """Return the singleton queue; backend selected by ORCH_QUEUE_BACKEND (default: supabase)."""
    global _instance
    if _instance is None:
        backend = os.environ.get("ORCH_QUEUE_BACKEND", "supabase").lower()
        cls = _BACKENDS.get(backend)
        if cls is None:
            raise ValueError(
                f"Unknown ORCH_QUEUE_BACKEND={backend!r}; choose from: {sorted(_BACKENDS)}"
            )
        _instance = cls()
    return _instance


def reset_queue() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    _instance = None
