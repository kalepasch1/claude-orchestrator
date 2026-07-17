"""Structured logging for the orchestrator runner.

Usage:
    import log
    _log = log.get(__name__)
    _log.info("claimed task %s", task_id)

Configurable via env:
    LOG_LEVEL   – DEBUG/INFO/WARNING/ERROR (default: INFO)
"""
import logging
import os
import socket
import threading

_hostname = socket.gethostname()
_lock = threading.Lock()
_configured = False


def _ensure_configured():
    global _configured
    if _configured:
        return
    with _lock:
        if _configured:
            return
        level = os.environ.get("LOG_LEVEL", "INFO").upper()
        fmt = (
            f"%(asctime)s [{_hostname}] %(levelname)-5s %(name)s | %(message)s"
        )
        logging.basicConfig(
            level=getattr(logging, level, logging.INFO),
            format=fmt,
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        _configured = True


def get(name: str) -> logging.Logger:
    """Return a named logger, configuring the root logger on first call."""
    _ensure_configured()
    return logging.getLogger(name)


def with_task(logger: logging.Logger, task_id: str = "") -> logging.LoggerAdapter:
    """Return a LoggerAdapter that prefixes messages with a task ID.

    Accepts None or empty string gracefully — returns an adapter with
    an empty task_id so callers never need a guard.
    """
    return logging.LoggerAdapter(logger, {"task_id": task_id or ""})
