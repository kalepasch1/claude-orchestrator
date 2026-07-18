#!/usr/bin/env python3
"""
events.py - structured event stream for the runner. All significant state transitions
(sentinel decisions, merge outcomes, task claims/finishes, governor decisions, deployments)
emit structured JSONL events to .runtime/events/<date>.jsonl for consumption by daily brief,
dashboard API, and fleet-RAG indexer.

emit(kind, **fields)         Append a timestamped event; handles rotation/size-capping.
read_events(date=None)       Read all events from a specific date (default: today).
read_recent(limit=100)       Read the last N events across all dates.
_rotate_if_needed()          Internal; called by emit() to cap file size (~100MB per day).
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import threading
from typing import Any, Union

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(os.path.dirname(HERE), ".runtime")
EVENTS_DIR = os.path.join(RUNTIME, "events")
MAX_FILE_SIZE = int(os.environ.get("ORCH_EVENT_FILE_SIZE_MB", "100")) * 1024 * 1024
MAX_BACKUPS_PER_DAY = int(os.environ.get("ORCH_EVENT_BACKUPS_PER_DAY", "3"))

_lock = threading.Lock()


def _event_path(date: Union[datetime.date, datetime.datetime, str, None] = None) -> str:
    """Return the JSONL file path for a given date (datetime.date or None for today)."""
    if date is None:
        date = datetime.date.today()
    elif isinstance(date, str):
        date = datetime.datetime.fromisoformat(date).date()
    elif isinstance(date, datetime.datetime):
        date = date.date()
    return os.path.join(EVENTS_DIR, f"{date.isoformat()}.jsonl")


def _rotate_if_needed(path: str) -> None:
    """If path exceeds MAX_FILE_SIZE, rotate to a numbered backup (.jsonl.0, .jsonl.1, ...)
    and truncate the current file. Maintains up to MAX_BACKUPS_PER_DAY backups per date."""
    if not os.path.exists(path):
        return
    try:
        size = os.path.getsize(path)
        if size < MAX_FILE_SIZE:
            return
        for i in range(MAX_BACKUPS_PER_DAY - 1, 0, -1):
            old = f"{path}.{i}"
            new = f"{path}.{i+1}"
            if os.path.exists(old):
                try:
                    os.remove(new) if os.path.exists(new) else None
                    os.rename(old, new)
                except OSError:
                    pass
        try:
            os.rename(path, f"{path}.0")
        except OSError:
            pass
        open(path, "w").close()
    except OSError:
        pass


def emit(kind: str, **fields: Any) -> bool:
    """Emit a structured event to the daily event stream.

    Args:
        kind: Event type (e.g., "sentinel:db-down", "train:merged", "task:claimed")
        **fields: Arbitrary key-value pairs (timestamp added automatically)

    Returns:
        True on success, False on error (fail-soft).
    """
    try:
        os.makedirs(EVENTS_DIR, exist_ok=True)
        with _lock:
            path = _event_path()
            _rotate_if_needed(path)
            event = {
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                "kind": kind,
                **fields
            }
            with open(path, "a") as f:
                f.write(json.dumps(event, separators=(",", ":")) + "\n")
            return True
    except Exception:
        return False


def read_events(date: Union[datetime.date, datetime.datetime, str, None] = None) -> list[dict[str, Any]]:
    """Read all events from a specific date. Returns list of dicts, or [] on error."""
    try:
        path = _event_path(date)
        if not os.path.exists(path):
            return []
        events = []
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return events
    except Exception:
        return []


def read_recent(limit: int = 100) -> list[dict[str, Any]]:
    """Read the last N events across all dates (most recent first).

    Scans event files in reverse chronological order until we have enough events.
    Returns list of dicts.
    """
    try:
        os.makedirs(EVENTS_DIR, exist_ok=True)
        files = sorted(os.listdir(EVENTS_DIR), reverse=True)
        events = []
        for f in files:
            if not f.endswith(".jsonl"):
                continue
            path = os.path.join(EVENTS_DIR, f)
            try:
                with open(path, "r") as file:
                    all_events = [json.loads(line.strip()) for line in file if line.strip()]
                    all_events.reverse()
                    events.extend(all_events)
                    if len(events) >= limit:
                        events = events[:limit]
                        return events
            except (OSError, json.JSONDecodeError):
                pass
        return events
    except Exception:
        return []


def stats() -> tuple[int, int, int]:
    """Return (total_events_count, disk_size_bytes, file_count)."""
    try:
        os.makedirs(EVENTS_DIR, exist_ok=True)
        total = 0
        size = 0
        count = 0
        for f in os.listdir(EVENTS_DIR):
            if f.endswith(".jsonl") or f.endswith((".jsonl.0", ".jsonl.1", ".jsonl.2")):
                path = os.path.join(EVENTS_DIR, f)
                size += os.path.getsize(path)
                count += 1
                with open(path, "r") as file:
                    total += sum(1 for _ in file if _.strip())
        return total, size, count
    except Exception:
        return 0, 0, 0


def invalidate() -> bool:
    """Clear all event files (for testing)."""
    try:
        import shutil
        if os.path.exists(EVENTS_DIR):
            shutil.rmtree(EVENTS_DIR)
        os.makedirs(EVENTS_DIR, exist_ok=True)
        return True
    except Exception:
        return False
