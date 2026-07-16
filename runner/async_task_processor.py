"""Asynchronous task processing for the orchestrator.

Provides non-blocking task execution with callbacks and queue management.
"""
import time
import logging
import threading
from typing import Dict, List, Any, Optional, Callable
from collections import deque

log = logging.getLogger(__name__)

class AsyncTask:
    def __init__(self, task_id: str, fn: Callable, args: tuple = (),
                 kwargs: dict = None):
        self.task_id = task_id
        self.fn = fn
        self.args = args
        self.kwargs = kwargs or {}
        self.status = "queued"
        self.result = None
        self.error: Optional[str] = None
        self.queued_at = time.time()
        self.started_at: Optional[float] = None
        self.completed_at: Optional[float] = None

class AsyncProcessor:
    def __init__(self, max_concurrent: int = 4):
        self._max_concurrent = max_concurrent
        self._queue: deque = deque()
        self._active: Dict[str, AsyncTask] = {}
        self._completed: List[AsyncTask] = []
        self._callbacks: List[Callable] = []

    def submit(self, task_id: str, fn: Callable, *args, **kwargs) -> AsyncTask:
        task = AsyncTask(task_id, fn, args, kwargs)
        self._queue.append(task)
        return task

    def on_complete(self, callback: Callable):
        self._callbacks.append(callback)

    def process_next(self) -> Optional[AsyncTask]:
        if not self._queue:
            return None
        if len(self._active) >= self._max_concurrent:
            return None
        task = self._queue.popleft()
        task.status = "running"
        task.started_at = time.time()
        self._active[task.task_id] = task
        try:
            task.result = task.fn(*task.args, **task.kwargs)
            task.status = "completed"
        except Exception as e:
            task.error = str(e)
            task.status = "failed"
        task.completed_at = time.time()
        del self._active[task.task_id]
        self._completed.append(task)
        for cb in self._callbacks:
            try:
                cb(task)
            except Exception:
                pass
        return task

    def process_all(self) -> List[AsyncTask]:
        results = []
        while self._queue:
            r = self.process_next()
            if r:
                results.append(r)
            else:
                break
        return results

    @property
    def pending_count(self) -> int:
        return len(self._queue)

    @property
    def active_count(self) -> int:
        return len(self._active)

    def get_stats(self) -> Dict[str, Any]:
        return {
            "pending": self.pending_count,
            "active": self.active_count,
            "completed": len(self._completed),
            "failed": sum(1 for t in self._completed if t.status == "failed"),
        }
