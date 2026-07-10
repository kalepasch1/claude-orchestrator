"""log_util.py — centralized logging facade for the runner.

Provides a consistent format and level across all modules. Call
get_logger(__name__) at module level; the first call configures the
root handler once via setup_logging().

Level is controlled by the ORCH_LOG_LEVEL env var (default: WARNING).
All modules that currently use print() for errors can migrate one call
at a time without changing fail-soft semantics.
"""
import logging
import os
import threading

_setup_lock = threading.Lock()
_configured = False

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DATE_FMT = "%Y-%m-%dT%H:%M:%S"


def setup_logging() -> None:
    """Configure the root logger once (idempotent, thread-safe)."""
    global _configured
    if _configured:
        return
    with _setup_lock:
        if _configured:
            return
        level_name = os.environ.get("ORCH_LOG_LEVEL", "WARNING").upper()
        level = getattr(logging, level_name, logging.WARNING)
        logging.basicConfig(level=level, format=_FORMAT, datefmt=_DATE_FMT)
        _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, configuring the root handler on first call."""
    setup_logging()
    return logging.getLogger(name or __name__)
