#!/usr/bin/env python3
"""Append-only, idempotent evidence bus for every autonomous control decision."""
import hashlib
import json
import time
import datetime

import db


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
        # Evidence must never make a safety control unavailable; callers retain a stable key
        # and reconciliation can replay it later.
        return {"idempotency_key": key, "persisted": False, "error": str(exc)}
    return {"idempotency_key": key, "persisted": True}


def events(kind=None, app=None, limit=1000):
    query = {"select": "*", "order": "created_at.desc", "limit": str(limit)}
    if kind: query["kind"] = f"eq.{kind}"
    if app: query["app"] = f"eq.{app}"
    try:
        return db.select("fleet_evidence_events", query) or []
    except Exception:
        return []
