#!/usr/bin/env python3
"""
zombie_reaper.py - terminal disposal of orphaned tasks.

`runner._reap_zombie_tasks()` already finds RUNNING tasks whose worker died and
hands them to `agentic_repair.repair_patch` for another attempt. That is the right
default: most stalls are transient and the work is worth resuming.

It is not the right *final* answer. A task whose runner has died repeatedly, or
whose repair budget is exhausted, gets rediscovered every reap cycle and requeued
forever — it never reaches a terminal state, so it stays in the RUNNING census,
keeps skewing throughput metrics, and keeps consuming a claim slot. This module is
the other half: given an explicit list of expired task ids, move each one to FAILED
and stop.

Deliberately narrow by design:

  * It takes ids the caller has already decided are expired. It does no detection
    of its own — detection lives in the reap loop, which has the heartbeat and
    cutoff context. A module that both detected and terminated would be a second,
    competing definition of "expired".
  * It is state-guarded. Between the caller's detection query and this write, the
    original worker may have come back and finished the task. Terminating a task
    that has since gone DONE would destroy real work, so the current state is
    re-read and anything no longer in the expected state is skipped.
  * It never raises. A reaper that throws on one bad id would abandon the rest of
    the batch, which is exactly the failure mode that produced the orphan backlog.

Usage:
    import zombie_reaper
    result = zombie_reaper.terminate_expired(["id-1", "id-2"])
    # -> {"terminated": [...], "skipped": [...], "missing": [...], "errored": [...]}

Env vars:
    ORCH_ZOMBIE_TERMINATE_ENABLED  "true" (default). "false" makes every call a
                                   dry run that reports what it *would* terminate.
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import log as _log_mod
    _log = _log_mod.get("zombie_reaper")
except Exception:  # pragma: no cover - logging must never be the failure
    class _NullLog:
        def _emit(self, *a, **k):
            pass
        info = warning = warn = error = debug = _emit
    _log = _NullLog()

FAILED_STATE = "FAILED"
EXPECTED_STATE = "RUNNING"
DEFAULT_REASON = "zombie-reaper: expired heartbeat"
_NOTE_MAX_BYTES = 1000


def _enabled():
    return os.environ.get("ORCH_ZOMBIE_TERMINATE_ENABLED", "true").lower() in (
        "1", "true", "yes", "on")


def _truncate(text, limit=_NOTE_MAX_BYTES):
    """Byte-bounded note truncation. Mirrors common_utils.truncate_string_at_bytes
    but is inlined so this module has no import-time dependency on the runner
    package — the reaper has to work even when the runner is the thing that broke."""
    try:
        from common_utils import truncate_string_at_bytes
        return truncate_string_at_bytes(text, limit)
    except Exception:
        raw = str(text or "").encode("utf-8", errors="replace")
        if len(raw) <= limit:
            return raw.decode("utf-8", errors="replace")
        return raw[:limit].decode("utf-8", errors="replace")


class ZombieReaper:
    """Terminates expired tasks against an injectable store.

    `store` is any object exposing the two methods this needs:
        select(table, params) -> list[dict]
        update(table, match, patch) -> anything
    which is exactly `runner/db.py`'s surface, so production passes `db` and tests
    pass an in-memory fake. Nothing here knows about HTTP, PostgREST, or Supabase.
    """

    def __init__(self, store=None, expected_state=EXPECTED_STATE,
                 failed_state=FAILED_STATE):
        self._lock = threading.Lock()
        self._store = store
        self.expected_state = expected_state
        self.failed_state = failed_state

    # ------------------------------------------------------------------ store

    def _resolve_store(self, store=None):
        """Late-bind `db` so importing this module never forces a DB connection."""
        if store is not None:
            return store
        if self._store is not None:
            return self._store
        import db as _db
        self._store = _db
        return self._store

    def _fetch(self, store, task_id):
        """Current row for `task_id`, or None when it no longer exists."""
        rows = store.select("tasks", {
            "select": "id,slug,state,note,account",
            "id": f"eq.{task_id}",
            "limit": "1",
        }) or []
        return rows[0] if rows else None

    # ------------------------------------------------------------- operation

    def terminate_expired(self, task_ids, reason=DEFAULT_REASON, store=None,
                          dry_run=None):
        """Move each expired task id to FAILED.

        Returns a dict of four id lists, so a caller can alert on `errored`
        without having to parse logs:

            terminated  written to FAILED
            skipped     still present but no longer in the expected state
                        (a concurrent writer got there first)
            missing     no such task — already deleted or purged
            errored     the store raised on this id specifically

        A warning naming the task id is logged for every id that is not
        terminated cleanly, because an orphan that cannot be disposed of is the
        condition an operator actually needs to see.
        """
        result = {"terminated": [], "skipped": [], "missing": [], "errored": []}

        ids = self._normalize(task_ids)
        if not ids:
            return result

        dry = (not _enabled()) if dry_run is None else bool(dry_run)

        try:
            store = self._resolve_store(store)
        except Exception as e:
            _log.error("zombie-reaper: no task store available (%s); nothing terminated", e)
            result["errored"] = list(ids)
            return result

        with self._lock:
            for task_id in ids:
                try:
                    row = self._fetch(store, task_id)
                except Exception as e:
                    _log.warning("zombie-reaper: task %s could not be read (%s); skipping",
                                 task_id, e)
                    result["errored"].append(task_id)
                    continue

                if row is None:
                    _log.warning("zombie-reaper: task %s no longer exists; skipping", task_id)
                    result["missing"].append(task_id)
                    continue

                state = str(row.get("state") or "")
                if state != self.expected_state:
                    _log.warning(
                        "zombie-reaper: task %s changed state to %s concurrently; skipping",
                        task_id, state or "<empty>")
                    result["skipped"].append(task_id)
                    continue

                if dry:
                    _log.warning("zombie-reaper: task %s would be terminated (dry run)", task_id)
                    result["terminated"].append(task_id)
                    continue

                try:
                    store.update("tasks", {"id": task_id}, {
                        "state": self.failed_state,
                        "note": self._note(row, reason),
                        "updated_at": "now()",
                    })
                except Exception as e:
                    _log.warning("zombie-reaper: task %s could not be terminated (%s); skipping",
                                 task_id, e)
                    result["errored"].append(task_id)
                    continue

                _log.warning("zombie-reaper: task %s terminated — %s", task_id, reason)
                result["terminated"].append(task_id)

        return result

    # ------------------------------------------------------------------ util

    @staticmethod
    def _normalize(task_ids):
        """Accept a single id, any iterable of ids, or None. Drop blanks and
        duplicates while preserving caller order — terminating the same id twice
        would emit a spurious 'changed state concurrently' warning on the second
        pass and make a clean run look like a race."""
        if task_ids is None:
            return []
        if isinstance(task_ids, (str, bytes)):
            task_ids = [task_ids]
        try:
            candidates = list(task_ids)
        except TypeError:
            return []
        seen, ordered = set(), []
        for raw in candidates:
            if raw is None:
                continue
            tid = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            tid = tid.strip()
            if not tid or tid in seen:
                continue
            seen.add(tid)
            ordered.append(tid)
        return ordered

    def _note(self, row, reason):
        """Append the reason to the existing note rather than overwriting it.

        The prior note is the only record of why the task was attempted; losing it
        turns a diagnosable orphan into an unexplained FAILED row."""
        existing = str(row.get("note") or "").strip()
        return _truncate(f"{existing} | {reason}".strip(" |") if existing else reason)


# ---------------------------------------------------------------------------
# Module-level singleton (repo convention: module functions delegate to one
# thread-safe instance, so callers never thread state through the call chain).
# The singleton is constructed with no store; `db` is resolved lazily on first
# use so importing this module cannot open a connection or fail at import time.
# ---------------------------------------------------------------------------
_reaper = ZombieReaper()


def terminate_expired(task_ids, reason=DEFAULT_REASON, store=None, dry_run=None):
    return _reaper.terminate_expired(task_ids, reason=reason, store=store,
                                     dry_run=dry_run)
