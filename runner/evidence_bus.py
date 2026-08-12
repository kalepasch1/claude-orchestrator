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
    """Every spooled line, split into parseable rows and unparseable raw lines.

    Malformed lines are kept verbatim rather than dropped: a half-written line
    from a crashed process is still evidence, and json.JSONDecodeError used to
    escape flush() entirely (the caller only guarded OSError).
    """
    rows, corrupt = [], []
    try:
        with open(_OUTBOX, encoding="utf-8") as outbox:
            for line in outbox:
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except (ValueError, TypeError):
                    corrupt.append(line.rstrip("\n"))
    except OSError:
        return [], []
    return rows, corrupt


def _write_outbox(rows, corrupt=()):
    try:
        os.makedirs(os.path.dirname(_OUTBOX), exist_ok=True)
        with open(_OUTBOX, "w", encoding="utf-8") as outbox:
            for row in rows:
                outbox.write(_canonical(row) + "\n")
            for line in corrupt:
                outbox.write(line + "\n")
        return True
    except OSError:
        return False


def backlog():
    """Outbox depth without delivering anything. Never raises.

    Returns {"pending", "corrupt", "oldest_age_s", "path"}. `oldest_age_s` is
    derived from the spooled rows' own timestamps when present, falling back to
    the file mtime, so a stuck outbox is visible even if rows carry no clock.
    """
    rows, corrupt = _read_outbox()
    oldest = None
    for row in rows:
        stamp = row.get("created_at") or row.get("occurred_at") if isinstance(row, dict) else None
        if not stamp:
            continue
        try:
            parsed = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            epoch = parsed.timestamp()
        except (ValueError, TypeError, OSError):
            continue
        oldest = epoch if oldest is None else min(oldest, epoch)
    if oldest is None and (rows or corrupt):
        try:
            oldest = os.path.getmtime(_OUTBOX)
        except OSError:
            oldest = None
    age = None if oldest is None else max(0, int(time.time() - oldest))
    return {"pending": len(rows), "corrupt": len(corrupt),
            "oldest_age_s": age, "path": _OUTBOX}


def flush(limit=500):
    """Replay the local outbox; DB uniqueness makes retry idempotent.

    `limit` bounds how many rows are ATTEMPTED per pass, never how many
    survive. The previous implementation truncated the read to `limit` and
    then rewrote the file from that slice alone, so an outbox deeper than the
    limit lost every row past it — silent evidence destruction in exactly the
    backlog case the outbox exists to survive. Undelivered and un-attempted
    rows are both carried forward.
    """
    rows, corrupt = _read_outbox()
    if not rows and not corrupt:
        return 0
    try:
        bound = max(0, int(limit))
    except (TypeError, ValueError):
        bound = 500
    attempted, deferred = rows[:bound], rows[bound:]
    delivered = 0
    remaining = []
    for row in attempted:
        try:
            db.insert("fleet_evidence_events", row)
            delivered += 1
        except Exception:
            remaining.append(row)
    _write_outbox(remaining + deferred, corrupt)
    return delivered


def events(kind=None, app=None, limit=1000):
    query = {"select": "*", "order": "created_at.desc", "limit": str(limit)}
    if kind: query["kind"] = f"eq.{kind}"
    if app: query["app"] = f"eq.{app}"
    try:
        return db.select("fleet_evidence_events", query) or []
    except Exception:
        return []
