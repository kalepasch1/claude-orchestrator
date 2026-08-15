#!/usr/bin/env python3
"""development_session_store.py — durable, append-only record of a development session.

WHAT WAS WRONG. `task_artifacts` keeps ONE row per slug and, on any DB error, writes a
JSON file under `.runtime/artifacts` on whichever Mac ran the task. Another host cannot
see it, so a release-critical record can exist only on a laptop that is asleep — and the
write reports success either way. It also stores a final snapshot, not a stream, so a
session that dies mid-flight leaves nothing to resume from.

WHAT THIS ADDS.
  * append-only events with a dense per-session `seq` and a caller idempotency key, so a
    redelivered event is absorbed rather than appended twice;
  * cursor pagination, so replaying >1000 events is a bounded walk, not one huge read;
  * artifacts recorded by digest + media type + producing adapter/runner/generation +
    task + commit + a DURABLE location;
  * resume/replay, retention and redaction;
  * `capture_compat`, so existing `task_artifacts` callers keep working.

DESIGN. Every store operation is injected (`store=`), so the whole module is unit-tested
with no database — the same seam `runner/enqueue.py` and `config_store.py` use.

FAIL-SOFT vs FAIL-LOUD. Reads degrade quietly. Release-critical WRITES do not: they raise
`DurabilityError` rather than falling back to local disk. A silent local fallback is the
exact defect this module exists to remove, so re-introducing one "to be safe" would be
the bug, not the safety net.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional

SESSIONS_TABLE = "development_sessions"
EVENTS_TABLE = "development_session_events"
ARTIFACTS_TABLE = "development_session_artifacts"

#: Hard ceiling on any single response, mirroring db.PAGE_SIZE. PostgREST returns at most
#: 1000 rows regardless of `limit`, so a larger request never widens the window — it only
#: hides that the response was cut off.
SERVER_PAGE_CAP = 1000

#: Default page size for cursor reads. Never allowed to exceed SERVER_PAGE_CAP.
PAGE_SIZE = min(int(os.environ.get("ORCH_SESSION_EVENT_PAGE", "500")), SERVER_PAGE_CAP)

#: Events older than this are eligible for retention pruning.
RETENTION_DAYS = int(os.environ.get("ORCH_SESSION_RETENTION_DAYS", "90"))

#: How many times an appender retries after losing a race for a sequence number.
MAX_SEQ_RETRIES = int(os.environ.get("ORCH_SESSION_SEQ_RETRIES", "8"))

_lock = threading.Lock()


class DurabilityError(RuntimeError):
    """A release-critical write could not be made durable.

    Raised instead of writing to local disk. The caller must decide what to do; silently
    degrading to a Mac-local file is what made the previous store untrustworthy.
    """


class SequenceExhausted(DurabilityError):
    """Too many appenders raced for the same ordinal."""


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

#: Payload keys whose values never belong in a durable, fleet-visible log.
_SECRET_KEY_RE = re.compile(
    r"(SECRET|TOKEN|PASSWORD|PASSWD|PWD|CREDENTIAL|_PAT\b|^PAT$|(^|_)KEY(_|$)|_KEY\b|"
    r"COOKIE|DSN|CONNECTION_?STRING|DATABASE_URL|AUTHORIZATION)", re.IGNORECASE)

#: Value shapes that are credentials whatever the key is called.
_SECRET_VALUE_RE = re.compile(
    r"(vcp_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-[A-Za-z0-9_\-]{20,}|sk_(live|test)_[A-Za-z0-9]{20,}|whsec_[A-Za-z0-9]{20,}"
    r"|xox[baprs]-[A-Za-z0-9\-]{20,}|AIza[A-Za-z0-9_\-]{30,}|AKIA[0-9A-Z]{16}"
    r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{20,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|postgres(ql)?://[^\s:]+:[^\s@]+@)")

REDACTED = "[REDACTED]"


def redact(payload: Any) -> Any:
    """Return a copy of `payload` with credential-shaped content removed.

    By key name AND by value shape, because an innocuous key is no evidence of innocuous
    content — the fleet_config incident found a live credential under a key literally
    named `key`. Recurses through dicts and lists; never mutates the caller's object,
    which would corrupt the very payload being logged.
    """
    if isinstance(payload, dict):
        out = {}
        for key, value in payload.items():
            if isinstance(key, str) and _SECRET_KEY_RE.search(key):
                out[key] = REDACTED
            else:
                out[key] = redact(value)
        return out
    if isinstance(payload, (list, tuple)):
        return [redact(item) for item in payload]
    if isinstance(payload, str) and _SECRET_VALUE_RE.search(payload):
        return REDACTED
    return payload


def contains_secret(payload: Any) -> bool:
    """True when `redact` would change anything. Used to set the `redacted` column."""
    return redact(payload) != payload


# ---------------------------------------------------------------------------
# Durable-location policy
# ---------------------------------------------------------------------------

#: Location schemes that another host can actually resolve.
DURABLE_SCHEMES = ("git:", "refs/", "https://", "http://", "s3://", "gs://", "supabase://")


def is_durable_location(location: str) -> bool:
    """True when `location` is resolvable from a host other than the one that wrote it.

    A bare filesystem path is NOT durable, however absolute it looks. `/Users/.../
    .runtime/artifacts/x.json` reads as a perfectly good path on every Mac in the fleet
    and resolves to the artifact on exactly one of them.
    """
    text = (location or "").strip()
    if not text:
        return False
    return text.startswith(DURABLE_SCHEMES)


# ---------------------------------------------------------------------------
# Store seam
# ---------------------------------------------------------------------------

class DbStore:
    """Default store: the fleet database. Every method is a thin `db` forward."""

    def __init__(self, db_module=None):
        self._db = db_module

    @property
    def db(self):
        if self._db is None:
            import db as _db
            self._db = _db
        return self._db

    def insert(self, table: str, row: Dict[str, Any]) -> Any:
        return self.db.insert(table, row)

    def select(self, table: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.db.select(table, params) or []

    def update(self, table: str, match: Dict[str, Any], patch: Dict[str, Any]) -> Any:
        return self.db.update(table, match, patch)

    def delete(self, table: str, match: Dict[str, Any]) -> Any:
        deleter = getattr(self.db, "delete", None)
        if deleter is None:
            raise DurabilityError("db module has no delete()")
        return deleter(table, match)


_default_store: Optional[DbStore] = None


def get_store() -> DbStore:
    global _default_store
    if _default_store is None:
        _default_store = DbStore()
    return _default_store


def _resolve(store) -> Any:
    return store if store is not None else get_store()


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def start_session(slug: str, host: str, project: str = None, adapter: str = None,
                  generation: int = 0, session_id: str = None, store=None) -> Dict[str, Any]:
    """Open (or re-open) a session. Returns the session row.

    Passing an existing `session_id` RESUMES: the row keeps its id and event history and
    takes the new generation, so "who is writing right now" is answerable without
    inferring it from timestamps.
    """
    if not slug or not host:
        raise ValueError("slug and host are required")
    store = _resolve(store)
    sid = session_id or str(uuid.uuid4())
    row = {
        "session_id": sid, "slug": slug, "project": project, "host": host,
        "adapter": adapter, "generation": int(generation or 0),
        "status": "active", "last_seq": 0,
        "created_at": _now(), "updated_at": _now(),
    }
    if session_id:
        existing = get_session(session_id, store=store)
        if existing:
            store.update(SESSIONS_TABLE, {"session_id": session_id}, {
                "status": "active", "host": host, "generation": int(generation or 0),
                "updated_at": _now(),
            })
            existing.update({"status": "active", "host": host,
                             "generation": int(generation or 0)})
            return existing
    try:
        store.insert(SESSIONS_TABLE, row)
    except Exception as exc:
        raise DurabilityError(f"could not open session {sid}: {exc}") from exc
    return row


def get_session(session_id: str, store=None) -> Optional[Dict[str, Any]]:
    store = _resolve(store)
    try:
        rows = store.select(SESSIONS_TABLE, {"select": "*",
                                             "session_id": f"eq.{session_id}", "limit": "1"})
    except Exception:
        return None
    return rows[0] if rows else None


def end_session(session_id: str, status: str = "completed", store=None) -> bool:
    if status not in ("completed", "failed", "abandoned"):
        raise ValueError("status must be completed, failed or abandoned")
    store = _resolve(store)
    try:
        store.update(SESSIONS_TABLE, {"session_id": session_id},
                     {"status": status, "ended_at": _now(), "updated_at": _now()})
        return True
    except Exception:
        return False


def reclaim_lost_sessions(host: str, store=None) -> List[str]:
    """Mark this host's still-'active' sessions as abandoned.

    Host loss is otherwise indistinguishable from a very slow session, and an event
    stream nobody will ever append to again should say so rather than look live forever.
    Returns the ids it reclaimed.
    """
    store = _resolve(store)
    try:
        rows = store.select(SESSIONS_TABLE, {
            "select": "session_id", "host": f"eq.{host}", "status": "eq.active",
            "order": "updated_at.asc", "limit": str(PAGE_SIZE)})
    except Exception:
        return []
    reclaimed = []
    for row in rows:
        sid = row.get("session_id")
        if sid and end_session(sid, "abandoned", store=store):
            reclaimed.append(sid)
    return reclaimed


# ---------------------------------------------------------------------------
# Events — append-only
# ---------------------------------------------------------------------------

def _next_seq(session_id: str, store) -> int:
    rows = store.select(EVENTS_TABLE, {
        "select": "seq", "session_id": f"eq.{session_id}",
        "order": "seq.desc", "limit": "1"})
    return (int(rows[0].get("seq") or 0) + 1) if rows else 1


def append_event(session_id: str, kind: str, payload: Dict[str, Any] = None,
                 idempotency_key: str = None, store=None) -> Dict[str, Any]:
    """Append one event. Returns the stored row (or the existing one on redelivery).

    CONCURRENCY. `seq` is assigned optimistically and the (session_id, seq) unique
    constraint arbitrates: a writer that loses the race sees the insert rejected and
    retries at the next ordinal. This is why the ordinal is enforced in the schema and
    not by reading-then-writing here — two appenders that both read `last_seq = 7` would
    otherwise both write 8, and one event would vanish with both writes reporting success.

    IDEMPOTENCY. `idempotency_key` defaults to a content digest, so an at-least-once
    transport that redelivers the same event finds the existing row and returns it
    instead of appending a duplicate.
    """
    if not session_id or not kind:
        raise ValueError("session_id and kind are required")
    store = _resolve(store)
    body = payload if payload is not None else {}
    safe = redact(body)
    was_redacted = safe != body
    key = idempotency_key or hashlib.sha256(
        json.dumps({"kind": kind, "payload": safe}, sort_keys=True,
                   default=str).encode()).hexdigest()

    existing = find_event_by_key(session_id, key, store=store)
    if existing:
        return existing

    last_error = None
    for _attempt in range(MAX_SEQ_RETRIES):
        seq = _next_seq(session_id, store)
        row = {
            "event_id": str(uuid.uuid4()), "session_id": session_id, "seq": seq,
            "idempotency_key": key, "kind": kind, "payload": safe,
            "redacted": was_redacted, "created_at": _now(),
        }
        try:
            store.insert(EVENTS_TABLE, row)
        except Exception as exc:
            last_error = exc
            # Lost the race, or the transport redelivered concurrently. Both are
            # resolvable by looking: if the key landed, that IS our event.
            duplicate = find_event_by_key(session_id, key, store=store)
            if duplicate:
                return duplicate
            time.sleep(0.01)
            continue
        try:
            store.update(SESSIONS_TABLE, {"session_id": session_id},
                         {"last_seq": seq, "updated_at": _now()})
        except Exception:
            # The event is durable; the high-water mark is a convenience for readers
            # and is recomputable from the events themselves.
            pass
        return row
    raise SequenceExhausted(
        f"could not append to {session_id} after {MAX_SEQ_RETRIES} attempts: {last_error}")


def find_event_by_key(session_id: str, idempotency_key: str,
                      store=None) -> Optional[Dict[str, Any]]:
    store = _resolve(store)
    try:
        rows = store.select(EVENTS_TABLE, {
            "select": "*", "session_id": f"eq.{session_id}",
            "idempotency_key": f"eq.{idempotency_key}", "limit": "1"})
    except Exception:
        return None
    return rows[0] if rows else None


def read_events(session_id: str, after_seq: int = 0, limit: int = None,
                store=None) -> Dict[str, Any]:
    """One page of events after `after_seq`, plus the cursor for the next page.

    Returns {"events": [...], "next_cursor": int|None, "has_more": bool}. `next_cursor`
    is None at the end of the stream, so a caller loops until it is None rather than
    guessing from a short page.
    """
    store = _resolve(store)
    # CLAMP to the server page cap. `has_more` is derived from `len(rows) >= size`, so a
    # caller passing limit=5000 against a backend that caps at 1000 would get 1000 rows,
    # compute `1000 >= 5000` as False, and stop paginating with the stream unfinished —
    # a silent truncation reported as a complete read. Asking for more than the cap never
    # widens the window, it only hides the cut, which is the exact shape that has caused
    # four outage-class failures on this fleet (see db.PAGE_SIZE).
    size = min(int(limit or PAGE_SIZE), SERVER_PAGE_CAP)
    try:
        rows = store.select(EVENTS_TABLE, {
            "select": "*", "session_id": f"eq.{session_id}",
            "seq": f"gt.{int(after_seq)}", "order": "seq.asc", "limit": str(size)})
    except Exception:
        return {"events": [], "next_cursor": None, "has_more": False}
    if not rows:
        return {"events": [], "next_cursor": None, "has_more": False}
    last = int(rows[-1].get("seq") or 0)
    has_more = len(rows) >= size
    return {"events": rows, "next_cursor": last if has_more else None,
            "has_more": has_more}


def replay(session_id: str, after_seq: int = 0, store=None) -> Iterable[Dict[str, Any]]:
    """Yield every event in order, paging to exhaustion.

    A generator on purpose: a session with 100k events must not have to fit in memory to
    be replayable, and the caller usually folds rather than collects.
    """
    cursor = int(after_seq)
    while True:
        page = read_events(session_id, after_seq=cursor, store=store)
        for event in page["events"]:
            yield event
        if not page["has_more"] or page["next_cursor"] is None:
            return
        cursor = page["next_cursor"]


def resume(session_id: str, host: str, generation: int = 0, store=None) -> Dict[str, Any]:
    """Reopen a session and report where to continue from.

    Returns {"session": row, "resume_after": int, "event_count": int}. `resume_after` is
    the last durable `seq`, computed from the EVENTS rather than the session's cached
    `last_seq` — the cache is a convenience and can lag if a writer died between the
    insert and the update.
    """
    session = get_session(session_id, store=store)
    if not session:
        raise DurabilityError(f"unknown session {session_id}")
    store_ = _resolve(store)
    last = 0
    count = 0
    try:
        rows = store_.select(EVENTS_TABLE, {
            "select": "seq", "session_id": f"eq.{session_id}",
            "order": "seq.desc", "limit": "1"})
        last = int(rows[0].get("seq") or 0) if rows else 0
    except Exception:
        last = int(session.get("last_seq") or 0)
    try:
        count = len(store_.select(EVENTS_TABLE, {
            "select": "event_id", "session_id": f"eq.{session_id}",
            "order": "seq.asc", "limit": "1000"}))
    except Exception:
        count = 0
    started = start_session(session.get("slug"), host, session.get("project"),
                            session.get("adapter"), generation,
                            session_id=session_id, store=store)
    return {"session": started, "resume_after": last, "event_count": count}


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

def record_artifact(digest: str, location: str, media_type: str = None,
                    session_id: str = None, slug: str = None, task_id: str = None,
                    commit_sha: str = None, adapter: str = None, runner_host: str = None,
                    generation: int = 0, byte_size: int = 0,
                    location_kind: str = None, store=None) -> Dict[str, Any]:
    """Record a durable artifact reference. Raises rather than accepting a local path.

    A release-critical artifact recorded as `/Users/.../.runtime/artifacts/x.json` looks
    fine in the table and resolves on exactly one Mac. Refusing it here is the whole
    point of the module.
    """
    if not digest:
        raise ValueError("digest is required")
    if not is_durable_location(location):
        raise DurabilityError(
            f"refusing to record a non-durable location {location!r}: another host cannot "
            f"resolve it. Publish to a git ref or object store first "
            f"(expected one of {', '.join(DURABLE_SCHEMES)}).")
    store = _resolve(store)
    row = {
        "artifact_id": str(uuid.uuid4()), "session_id": session_id, "slug": slug,
        "task_id": task_id, "commit_sha": commit_sha, "digest": digest,
        "media_type": media_type or "application/octet-stream",
        "byte_size": int(byte_size or 0), "adapter": adapter,
        "runner_host": runner_host, "generation": int(generation or 0),
        "location": location, "location_kind": location_kind or _location_kind(location),
        "redacted": False, "created_at": _now(),
    }
    try:
        store.insert(ARTIFACTS_TABLE, row)
    except Exception as exc:
        existing = find_artifact(digest, location, store=store)
        if existing:
            return existing
        raise DurabilityError(f"could not record artifact {digest[:12]}: {exc}") from exc
    return row


def _location_kind(location: str) -> str:
    text = (location or "").strip()
    if text.startswith(("git:", "refs/")):
        return "git_ref"
    if text.startswith(("s3://", "gs://", "supabase://")):
        return "object_store"
    if text.startswith(("https://", "http://")):
        return "url"
    return "unknown"


def find_artifact(digest: str, location: str = None, store=None) -> Optional[Dict[str, Any]]:
    store = _resolve(store)
    params = {"select": "*", "digest": f"eq.{digest}", "order": "created_at.desc",
              "limit": "1"}
    if location:
        params["location"] = f"eq.{location}"
    try:
        rows = store.select(ARTIFACTS_TABLE, params)
    except Exception:
        return None
    return rows[0] if rows else None


def digest_bytes(data: bytes) -> str:
    """Content address for artifact bytes."""
    return hashlib.sha256(data if isinstance(data, bytes)
                          else str(data).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def prune_events(older_than_days: int = None, store=None) -> int:
    """Delete events older than the retention window. Returns rows requested for delete.

    Sessions and artifacts are NOT pruned: an artifact reference is the durable record
    the whole module exists to keep, and a session row is a few hundred bytes. Only the
    event stream grows without bound.
    """
    store = _resolve(store)
    days = int(older_than_days if older_than_days is not None else RETENTION_DAYS)
    if days <= 0:
        return 0
    import datetime
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=days)).isoformat()
    try:
        rows = store.select(EVENTS_TABLE, {
            "select": "event_id", "created_at": f"lt.{cutoff}", "limit": str(PAGE_SIZE)})
    except Exception:
        return 0
    deleted = 0
    for row in rows:
        try:
            store.delete(EVENTS_TABLE, {"event_id": row["event_id"]})
            deleted += 1
        except Exception:
            break
    return deleted


# ---------------------------------------------------------------------------
# task_artifacts compatibility
# ---------------------------------------------------------------------------

def capture_compat(slug: str, artifacts: Dict[str, Any], session_id: str = None,
                   host: str = None, store=None) -> Dict[str, Any]:
    """Bridge a `task_artifacts.capture()` result into this store.

    Existing callers keep their shape; the durable half is recorded here. The artifact is
    keyed on `artifact_ref` (the immutable git ref task_refs publishes) rather than on the
    branch, because a branch moves and a ref does not.

    Returns {"artifact": row|None, "skipped": reason|None} — skipping is explicit so a
    caller can tell "nothing to record" from "recorded".
    """
    artifacts = artifacts or {}
    ref = artifacts.get("artifact_ref") or ""
    if not ref:
        return {"artifact": None, "skipped": "no immutable artifact_ref was published"}
    diff = artifacts.get("patch_diff") or ""
    row = record_artifact(
        digest=artifacts.get("patch_id") or digest_bytes(diff.encode()),
        location=ref if ref.startswith(("refs/", "git:")) else f"git:{ref}",
        media_type="text/x-diff",
        session_id=session_id, slug=slug,
        commit_sha=artifacts.get("commit_sha"),
        runner_host=host, byte_size=int(artifacts.get("diff_bytes") or 0),
        store=store)
    return {"artifact": row, "skipped": None}


__all__ = [
    "DurabilityError", "SequenceExhausted",
    "start_session", "get_session", "end_session", "resume", "reclaim_lost_sessions",
    "append_event", "read_events", "replay", "find_event_by_key",
    "record_artifact", "find_artifact", "digest_bytes", "is_durable_location",
    "redact", "contains_secret", "prune_events", "capture_compat",
]
