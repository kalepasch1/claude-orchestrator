#!/usr/bin/env python3
"""
branch_recovery_ledger.py — durable Supabase record of what the branch sweeps did.

WHY THIS EXISTS
---------------
`git_auto_branch.run()` archives, deletes and rebases branches on every pass, then
`print()`s three integers and returns them. The counts die with the process. When a
branch later turns out to be missing, nothing anywhere says whether this sweep archived
it, when, from which repo, or under what reason — so the fleet re-discovers the loss,
queues a recovery task, and pays for the investigation again. That exact loop is why
`branch_durability.safe_delete` exists at all: it archives the tip so the objects
survive. It returns a dict "so callers can log it" — and no caller ever did.

This module is that caller. Every archive/share/delete/rebase becomes an append-only
row in `resource_events` (an existing table — no DDL, no migration), and the owning
task's `note` is stamped so the recovery is visible from the queue the operator reads.

Design constraints this file follows deliberately:

  * **Fail-soft throughout.** A ledger that raises would wedge the sweep it observes.
    Every public function returns a result dict and never propagates an exception.
    Losing a log line is survivable; losing the sweep is not.
  * **Append-only for the ledger.** Recovery history is evidence. Rows are inserted,
    never updated or deleted.
  * **Never touches task state.** Only `note` is patched. A ledger module that could
    move a task between states would be a second, unaudited scheduler.
  * **Kill-switchable.** `ORCH_BRANCH_RECOVERY_LEDGER=false` disables writes without
    a deploy, per the fleet-config convention.

Public API
----------
    log_recovery_action(action, branch, *, repo, ...)  -> dict
    log_safe_delete(result, *, repo, ...)              -> dict
    mark_branch_recovered(slug, branch, *, detail)     -> dict
    log_sweep_summary(counts, *, repo)                 -> dict
    recent_actions(limit=50, *, branch="")             -> list

Environment
-----------
    ORCH_BRANCH_RECOVERY_LEDGER      Kill switch (default: true)
    ORCH_BRANCH_LEDGER_DETAIL_LIMIT  Max detail chars per row (default: 2000)
"""
from __future__ import annotations

import json
import os

EVENT_TABLE = "resource_events"

# One namespace for every row this module writes, so the whole recovery history is a
# single indexed prefix query rather than a scan for known action names.
KIND = "branch_recovery"

DETAIL_LIMIT = int(os.environ.get("ORCH_BRANCH_LEDGER_DETAIL_LIMIT", "2000"))

# The vocabulary of things a sweep can do to a branch. Kept closed so a typo in a
# caller shows up as "unknown" in the ledger instead of inventing a silent new action.
ACTIONS = ("archived", "shared", "deleted", "rebased", "skipped", "recovered",
           "sweep_summary")


def _enabled() -> bool:
    return os.environ.get("ORCH_BRANCH_RECOVERY_LEDGER", "true").strip().lower() \
        not in ("0", "false", "no", "off")


def _db():
    """The shared db singleton, or None. Never raises: callers degrade to no-op."""
    try:
        import db as _module
        return _module
    except Exception:  # noqa: BLE001 — fail-soft: no DB means no ledger, not a crash
        return None


def _truncate(text: str) -> str:
    text = "" if text is None else str(text)
    return text if len(text) <= DETAIL_LIMIT else text[:DETAIL_LIMIT - 3] + "..."


def _detail(payload: dict) -> str:
    """Serialize a payload compactly, falling back to repr rather than failing."""
    try:
        return _truncate(json.dumps(payload, sort_keys=True, default=str))
    except Exception:  # noqa: BLE001 — fail-soft
        return _truncate(repr(payload))


# ── Writes ──────────────────────────────────────────────────────────────────

def log_recovery_action(action: str, branch: str, *, repo: str = "", slug: str = "",
                        reason: str = "", ok: bool = True, extra: dict = None) -> dict:
    """Append one branch-recovery event. Returns {"logged": bool, "error": str|None}."""
    out = {"logged": False, "error": None, "action": action, "branch": branch}
    if not _enabled():
        out["error"] = "disabled by ORCH_BRANCH_RECOVERY_LEDGER"
        return out
    if not branch:
        out["error"] = "no branch given"
        return out

    if action not in ACTIONS:
        # Recorded, not rejected — an unrecognised action is still evidence, and
        # dropping it would hide exactly the case worth seeing.
        action = f"unknown:{action}"

    database = _db()
    if database is None:
        out["error"] = "db unavailable"
        return out

    payload = {"branch": branch, "repo": repo, "slug": slug, "reason": reason, "ok": ok}
    if extra:
        payload.update(extra)

    try:
        database.insert(EVENT_TABLE, {
            "kind": KIND,
            "action": action,
            "value": 1 if ok else 0,
            "detail": _detail(payload),
        }, upsert=False)
    except Exception as exc:  # noqa: BLE001 — fail-soft: never wedge the sweep
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    out["logged"] = True
    return out


def log_safe_delete(result: dict, *, repo: str = "", slug: str = "") -> dict:
    """Turn a `branch_durability.safe_delete()` dict into ledger rows.

    One row per thing that actually happened, so "archived but not deleted" is legible
    afterwards instead of collapsing into a single ambiguous outcome.
    """
    out = {"logged": [], "error": None}
    result = result or {}
    branch = result.get("branch") or ""
    if not branch:
        out["error"] = "result has no branch"
        return out

    reason = result.get("reason") or ""
    common = {"repo": repo, "slug": slug, "reason": reason}

    if result.get("archived"):
        out["logged"].append("archived")
        log_recovery_action("archived", branch, ok=True, **common,
                            extra={"archived": result.get("archived"),
                                   "durable": bool(result.get("durable"))})
    if result.get("shared"):
        out["logged"].append("shared")
        log_recovery_action("shared", branch, ok=True, **common)

    deleted = bool(result.get("local_deleted"))
    out["logged"].append("deleted" if deleted else "skipped")
    log_recovery_action("deleted" if deleted else "skipped", branch, ok=deleted, **common,
                        extra={"remote_deleted": bool(result.get("remote_deleted")),
                               "durable": bool(result.get("durable")),
                               "error": result.get("error") or ""})
    return out


def mark_branch_recovered(slug: str, branch: str = "", *, detail: str = "",
                          repo: str = "") -> dict:
    """Stamp the owning task's note so the recovery is visible from the queue.

    Only `note` is patched — never `state`. Task state belongs to the scheduler; a
    ledger that could move tasks between states would be a second, unaudited one.
    """
    out = {"marked": False, "logged": False, "error": None, "slug": slug}
    if not _enabled():
        out["error"] = "disabled by ORCH_BRANCH_RECOVERY_LEDGER"
        return out
    if not slug:
        out["error"] = "no slug given"
        return out

    branch = branch or f"agent/{slug}"
    ledger = log_recovery_action("recovered", branch, repo=repo, slug=slug,
                                 reason=detail, ok=True)
    out["logged"] = ledger["logged"]

    database = _db()
    if database is None:
        out["error"] = "db unavailable"
        return out

    stamp = _truncate(f"branch_recovery_ledger: {branch} recovered"
                      + (f" — {detail}" if detail else ""))
    try:
        database.update("tasks", {"slug": f"eq.{slug}"}, {"note": stamp})
    except Exception as exc:  # noqa: BLE001 — fail-soft
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    out["marked"] = True
    return out


def log_sweep_summary(counts: dict, *, repo: str = "") -> dict:
    """One row per sweep pass, so an empty sweep is distinguishable from no sweep."""
    out = {"logged": False, "error": None}
    if not _enabled():
        out["error"] = "disabled by ORCH_BRANCH_RECOVERY_LEDGER"
        return out
    database = _db()
    if database is None:
        out["error"] = "db unavailable"
        return out

    counts = counts or {}
    total = 0
    for value in counts.values():
        try:
            total += int(value)
        except (TypeError, ValueError):
            continue

    try:
        database.insert(EVENT_TABLE, {
            "kind": KIND,
            "action": "sweep_summary",
            "value": total,
            "detail": _detail({"repo": repo, **counts}),
        }, upsert=False)
    except Exception as exc:  # noqa: BLE001 — fail-soft
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    out["logged"] = True
    return out


# ── Reads ───────────────────────────────────────────────────────────────────

def recent_actions(limit: int = 50, *, branch: str = "") -> list:
    """Most recent recovery events, newest first. Fail-soft: empty list on any error."""
    database = _db()
    if database is None:
        return []
    try:
        rows = database.select(EVENT_TABLE, {
            "select": "id,kind,action,value,detail,created_at",
            "kind": f"eq.{KIND}",
            "order": "created_at.desc",
            "limit": str(max(1, int(limit))),
        }) or []
    except Exception:  # noqa: BLE001 — fail-soft
        return []
    if not branch:
        return rows
    return [r for r in rows if branch in (r.get("detail") or "")]
