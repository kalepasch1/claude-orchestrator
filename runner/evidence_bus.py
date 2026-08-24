#!/usr/bin/env python3
"""Append-only, idempotent evidence bus for every autonomous control decision."""
import hashlib
import json
import time
import datetime
import os

import db

_OUTBOX = os.path.join(os.environ.get("CLAUDE_ORCH_HOME", "/private/tmp"), "evidence-outbox.jsonl")


def _canonical(value):
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"), default=str)


def idempotency_key(app, kind, subject, payload):
    raw = f"{app}|{kind}|{subject}|{_canonical(payload)}"
    return hashlib.sha256(raw.encode()).hexdigest()


def append(app, kind, subject, payload=None, parent_key=None, key=None):
    """Persist an immutable event. Duplicate delivery is harmless due to the unique key."""
    payload = payload or {}
    key = key or idempotency_key(app, kind, subject, payload)
    row = {"app": app or "ORCHESTRATOR", "kind": kind, "subject": str(subject or ""),
           "payload": payload, "parent_key": parent_key, "idempotency_key": key,
           "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        db.insert("fleet_evidence_events", row)
    except Exception as exc:
        _spool(row)
        return {"idempotency_key": key, "persisted": False, "error": str(exc)}
    return {"idempotency_key": key, "persisted": True}


def _spool(row):
    """Durable local outbox: a transient DB failure cannot silently discard evidence."""
    try:
        os.makedirs(os.path.dirname(_OUTBOX), exist_ok=True)
        with open(_OUTBOX, "a", encoding="utf-8") as outbox:
            outbox.write(_canonical(row) + "\n")
    except OSError:
        pass


def _read_outbox():
    """(rows, corrupt_lines) from the local outbox. A missing file reads as empty.

    A line that is not a JSON object is NEVER discarded: it is evidence we failed to
    write correctly, and deleting it is the one outcome the outbox exists to prevent.
    It is carried forward verbatim and counted, so backlog() can raise the alarm.
    """
    rows, corrupt = [], []
    try:
        with open(_OUTBOX, encoding="utf-8") as outbox:
            for line in outbox:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    corrupt.append(line.rstrip("\n"))
                    continue
                (rows if isinstance(row, dict) else corrupt).append(
                    row if isinstance(row, dict) else line.rstrip("\n"))
    except OSError:
        return [], []
    return rows, corrupt


def _rewrite_outbox(rows, corrupt):
    """Replace the outbox with exactly `rows` + the corrupt lines we could not parse."""
    try:
        with open(_OUTBOX, "w", encoding="utf-8") as outbox:
            for row in rows:
                outbox.write(_canonical(row) + "\n")
            for line in corrupt:
                outbox.write(line + "\n")
    except OSError:
        pass


def backlog():
    """Depth, corruption and age of the oldest undelivered row in the local outbox.

    Read-only and total: a missing or unreadable outbox is an empty one, never an
    exception, because this is polled from health/readiness handlers.
    """
    rows, corrupt = _read_outbox()
    now = time.time()
    oldest = None
    for row in rows:
        # `observed_at` is what _spool writes; `created_at` is the DB column name and
        # appears on rows spooled back from a read of fleet_evidence_events.
        stamp = row.get("observed_at") or row.get("created_at")
        if not stamp:
            continue
        try:
            parsed = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            continue
        age = max(0, int(now - parsed.timestamp()))
        oldest = age if oldest is None else max(oldest, age)
    return {"pending": len(rows), "corrupt": len(corrupt),
            "oldest_age_s": oldest, "path": _OUTBOX}


def flush(limit=500):
    """Replay the local outbox; DB uniqueness makes retry idempotent.

    `limit` bounds how many rows are ATTEMPTED, not how many survive. The previous
    version read `[:limit]` rows and then rewrote the whole file from that truncated
    slice, so every row past the limit was destroyed by a successful flush — the exact
    silent evidence loss the outbox exists to prevent. Un-attempted rows are carried
    forward here, so a backlog deeper than one pass drains over several passes instead.
    """
    rows, corrupt = _read_outbox()
    if not rows and not corrupt:
        return 0
    try:
        limit = max(0, int(limit))
    except (TypeError, ValueError):
        limit = 500
    attempted, deferred = rows[:limit], rows[limit:]
    delivered = 0
    remaining = []
    for row in attempted:
        try:
            db.insert("fleet_evidence_events", row)
            delivered += 1
        except Exception:
            remaining.append(row)
    if delivered:
        # Nothing changed when nothing was delivered, and not rewriting keeps the
        # window in which a concurrent _spool() append could be lost as small as possible.
        _rewrite_outbox(remaining + deferred, corrupt)
    return delivered


def events(kind=None, app=None, limit=1000):
    query = {"select": "*", "order": "created_at.desc", "limit": str(limit)}
    if kind: query["kind"] = f"eq.{kind}"
    if app: query["app"] = f"eq.{app}"
    try:
        return db.select("fleet_evidence_events", query) or []
    except Exception:
        return []
