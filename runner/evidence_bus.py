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


def flush(limit=500):
    """Replay the local outbox; DB uniqueness makes retry idempotent."""
    try:
        with open(_OUTBOX, encoding="utf-8") as outbox:
            rows = [json.loads(line) for line in outbox if line.strip()][:limit]
    except OSError:
        return 0
    delivered = 0
    remaining = []
    for row in rows:
        try:
            db.insert("fleet_evidence_events", row)
            delivered += 1
        except Exception:
            remaining.append(row)
    try:
        with open(_OUTBOX, "w", encoding="utf-8") as outbox:
            for row in remaining:
                outbox.write(_canonical(row) + "\n")
    except OSError:
        pass
    return delivered


def events(kind=None, app=None, limit=1000):
    query = {"select": "*", "order": "created_at.desc", "limit": str(limit)}
    if kind: query["kind"] = f"eq.{kind}"
    if app: query["app"] = f"eq.{app}"
    try:
        return db.select("fleet_evidence_events", query) or []
    except Exception:
        return []
