"""structured_log.py — JSON-structured logging foundation for the runner.

The runner already has two plain-text logging facades (``log.py`` and
``log_util.py``). Neither emits machine-parseable records, so fleet-wide log
aggregation has to scrape free-form message strings. This module is the
structured foundation that error-handling work builds on top of.

Every record is a single JSON object on one line::

    {"timestamp": "2026-08-06T20:41:03.412Z", "severity": "INFO",
     "logger": "runner.decompose", "message": "claimed task",
     "context": {"task_id": "abc", "step": 3}}

Usage::

    from structured_log import get_logger

    log = get_logger(__name__)
    log.info("claimed task", extra={"context": {"task_id": task_id}})

    # Or bind context once and let every call inherit it:
    task_log = child_logger(log, task_id=task_id, step="decompose")
    task_log.info("iteration complete", extra={"context": {"iteration": 4}})

Level is read from ``ORCH_LOG_LEVEL``, falling back to ``LOG_LEVEL`` (which
``log.py`` already honours), defaulting to INFO.

This module is additive: it configures its own handler on a dedicated logger
tree and does not touch the root logger, so importing it cannot change the
output of modules still using ``log.py`` or ``log_util.py``.
"""

from __future__ import annotations

import datetime as _datetime
import json
import logging
import os
import sys
import threading
from typing import Any, Mapping

__all__ = [
    "DEFAULT_LEVEL",
    "JsonFormatter",
    "StructuredLoggerAdapter",
    "child_logger",
    "get_logger",
    "resolve_level",
]

DEFAULT_LEVEL = "INFO"

#: Attributes ``logging.LogRecord`` sets itself. Anything else found on a
#: record was injected by the caller via ``extra=`` and is worth emitting.
_RESERVED_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"asctime", "message", "context", "taskName"}

_lock = threading.Lock()
_configured_roots: set[str] = set()


def resolve_level(env: Mapping[str, str] | None = None) -> int:
    """Resolve the numeric log level from the environment.

    ``ORCH_LOG_LEVEL`` wins, then ``LOG_LEVEL``, then :data:`DEFAULT_LEVEL`.
    An unrecognised name falls back to the default rather than raising — log
    configuration must never be the reason a runner fails to start.
    """
    source = os.environ if env is None else env
    name = (source.get("ORCH_LOG_LEVEL") or source.get("LOG_LEVEL") or DEFAULT_LEVEL)
    level = logging.getLevelName(str(name).strip().upper())
    if not isinstance(level, int):
        level = logging.getLevelName(DEFAULT_LEVEL)
    return level


def _utc_timestamp(created: float) -> str:
    """Render a record's creation time as an ISO-8601 UTC string in ms."""
    moment = _datetime.datetime.fromtimestamp(created, _datetime.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


class JsonFormatter(logging.Formatter):
    """Format a :class:`logging.LogRecord` as one line of JSON.

    Always emits ``timestamp``, ``severity``, ``logger``, ``message`` and
    ``context``. ``context`` merges, in order: context bound to the logger via
    :func:`child_logger`, an explicit ``extra={"context": {...}}`` mapping, and
    any other non-reserved ``extra=`` keys. Exceptions add an ``exception``
    block with the type, message and formatted traceback.
    """

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload: dict[str, Any] = {
            "timestamp": _utc_timestamp(record.created),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "context": self._build_context(record),
        }

        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            payload["exception"] = {
                "type": getattr(exc_type, "__name__", str(exc_type)),
                "message": str(exc_value),
                "traceback": self.formatException(record.exc_info),
            }

        return json.dumps(payload, default=self._coerce, sort_keys=True)

    def _build_context(self, record: logging.LogRecord) -> dict[str, Any]:
        context: dict[str, Any] = {}

        bound = getattr(record, "context", None)
        if isinstance(bound, Mapping):
            context.update(bound)

        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_ATTRS and not key.startswith("_"):
                context[key] = value

        return context

    @staticmethod
    def _coerce(value: Any) -> str:
        """Last-resort serialiser so a non-JSON value never drops a log line."""
        return repr(value)


class StructuredLoggerAdapter(logging.LoggerAdapter):
    """A logger carrying a bound ``context`` dict that every call inherits.

    Per-call context is merged over the bound context, so a call may override
    an inherited field without mutating the adapter.
    """

    def __init__(self, logger: logging.Logger, context: Mapping[str, Any]):
        super().__init__(logger, dict(context))

    @property
    def context(self) -> dict[str, Any]:
        """The context bound to this adapter (a copy; safe to mutate)."""
        return dict(self.extra or {})

    def process(self, msg: Any, kwargs: dict[str, Any]):
        extra = dict(kwargs.get("extra") or {})
        merged = dict(self.extra or {})

        call_context = extra.pop("context", None)
        if isinstance(call_context, Mapping):
            merged.update(call_context)
        merged.update(extra)

        kwargs["extra"] = {"context": merged}
        return msg, kwargs

    def bind(self, **fields: Any) -> "StructuredLoggerAdapter":
        """Return a further-nested adapter with ``fields`` added."""
        return child_logger(self, **fields)


def _configure(logger: logging.Logger) -> None:
    """Attach a JSON handler to a top-level logger exactly once."""
    root_name = logger.name.split(".")[0]
    if root_name in _configured_roots:
        return

    with _lock:
        if root_name in _configured_roots:
            return

        root = logging.getLogger(root_name)
        if not any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(JsonFormatter())
            root.addHandler(handler)

        root.setLevel(resolve_level())
        # Own tree: do not double-emit through the root logger's plain-text
        # handlers installed by log.py / log_util.py.
        root.propagate = False
        _configured_roots.add(root_name)


def get_logger(name: str, **context: Any) -> logging.Logger | StructuredLoggerAdapter:
    """Return a JSON-emitting logger for ``name``.

    With ``context`` keyword arguments, returns a :class:`StructuredLoggerAdapter`
    with those fields bound; without, returns the plain :class:`logging.Logger`.
    """
    logger = logging.getLogger(name or __name__)
    _configure(logger)
    if context:
        return StructuredLoggerAdapter(logger, context)
    return logger


def child_logger(
    parent: logging.Logger | StructuredLoggerAdapter,
    **fields: Any,
) -> StructuredLoggerAdapter:
    """Return a child logger carrying ``fields`` merged over the parent context.

    Accepts either a plain logger or another :class:`StructuredLoggerAdapter`,
    so contexts nest::

        base = get_logger(__name__, service="runner")
        task = child_logger(base, task_id="t1")
        step = child_logger(task, step="decompose")   # service + task_id + step
    """
    if isinstance(parent, StructuredLoggerAdapter):
        merged = parent.context
        merged.update(fields)
        return StructuredLoggerAdapter(parent.logger, merged)

    _configure(parent)
    return StructuredLoggerAdapter(parent, fields)
