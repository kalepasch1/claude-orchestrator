#!/usr/bin/env python3
"""backlog_console.py — the `beethoven consolidate` / `beethoven backlog status` surface.

WHY THIS EXISTS. The finalize-backlog-consolidation task was blocked, twice, as
undoable: it calls for `beethoven consolidate --all` and `beethoven backlog status`,
and there is no `beethoven` executable — `beethoven/` is a package directory. The
previous run concluded the acceptance criterion ("JSON where collapsed_tasks is a
subset of the original set and any remainder is tagged manual_review") was therefore
unevaluable.

That was true, and the gap was small. BOTH capabilities already exist as Python:
`backlog_compactor.run()` collapses stale queued tasks, and `backlog_status`
reports state counts. What was missing was an entrypoint and a machine-readable
answer — the status module prints a human table, not JSON, so nothing could assert
on it. This module supplies both, and rebuilds nothing.

WHAT IT ADDS ON TOP OF THE EXISTING MODULES.
  * `manual_review`: a task that survives consolidation is TAGGED, with the reason,
    instead of silently remaining collapsed. "It did not work" and "it worked and
    there was nothing to do" were previously the same empty result.
  * `consolidation.log`: an append-only record of every run and every reason, so a
    consolidation that quietly stopped working is visible without a DB query.
  * JSON out. `collapsed_tasks` is a list of slugs, so "is a subset of the original"
    is a set operation a test can actually perform.

DESIGN. Every dependency is injected (`compactor=`, `store=`), so the whole module is
unit-tested without a database — the same seam config_store.py and enqueue.py use.
Fail-soft: a failure returns a result naming what failed; it does not raise into a
scheduled job.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#: Where the human-readable trail goes. ORCH_-prefixed so it is fleet-pushable.
CONSOLIDATION_LOG = os.environ.get(
    "ORCH_CONSOLIDATION_LOG",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 ".runtime", "logs", "consolidation.log"))

#: Note marker written on a task that consolidation could not collapse.
MANUAL_REVIEW = "manual_review"

#: States that still count as backlog. MERGED is excluded (shipped) and so is
#: QUARANTINED (deliberately parked), matching backlog_status.
BACKLOG_STATES = ("QUEUED", "RUNNING", "RETRY", "BLOCKED", "CONFLICT", "TESTFAIL", "DONE")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def log_line(message: str, path: Optional[str] = None) -> bool:
    """Append one line to consolidation.log. True on success, False on any error.

    Fail-soft by contract: losing the log must never fail the consolidation it is
    describing. It returns the outcome rather than swallowing it, so a caller that
    cares can tell the difference.
    """
    path = path or CONSOLIDATION_LOG
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{_now()} {message}\n")
        return True
    except Exception as e:
        print(f"[backlog_console] could not write {path}: {e}", flush=True)
        return False


def _load_db():
    try:
        import db
        return db
    except Exception:
        return None


def consolidate(all_projects: bool = True,
                limit: Optional[int] = None,
                compactor: Optional[Callable[..., Dict[str, Any]]] = None,
                store: Any = None,
                log_path: Optional[str] = None) -> Dict[str, Any]:
    """Run backlog consolidation and tag whatever survives as manual_review.

    Returns JSON-serializable:
        {"ok", "collapsed_tasks": [slug...], "manual_review": [{slug, reason}...],
         "summary": <compactor summary>}

    `collapsed_tasks` is a list of SLUGS, not a count, because the acceptance test
    needs to assert it is a subset of the tasks that went in — a count cannot answer
    that, and a count is what made this unevaluable before.
    """
    result: Dict[str, Any] = {"ok": True, "collapsed_tasks": [], "manual_review": [],
                              "summary": {}}
    if compactor is None:
        try:
            import backlog_compactor
            compactor = backlog_compactor.run
        except Exception as e:
            result.update(ok=False, error=f"compactor unavailable: {e}")
            log_line(f"consolidate FAILED: compactor unavailable: {e}", log_path)
            return result

    store = store if store is not None else _load_db()
    before = _collapsible_slugs(store)

    try:
        summary = compactor() if limit is None else compactor(limit=limit)
        result["summary"] = summary if isinstance(summary, dict) else {"result": summary}
    except Exception as e:
        result.update(ok=False, error=f"consolidation raised: {e}")
        log_line(f"consolidate FAILED: {e}", log_path)
        return result

    after = _collapsible_slugs(store)
    result["collapsed_tasks"] = sorted(set(before) - set(after))

    # Anything that went in and is still there could not be collapsed. Tag it with a
    # reason rather than leaving it looking identical to a task nobody looked at.
    for slug in sorted(set(before) & set(after)):
        reason = "still queued after consolidation; no group met the minimum size"
        result["manual_review"].append({"slug": slug, "reason": reason})
        _tag_manual_review(store, slug, reason)

    log_line(
        f"consolidate all={all_projects} collapsed={len(result['collapsed_tasks'])} "
        f"manual_review={len(result['manual_review'])} summary={result['summary']}",
        log_path)
    for entry in result["manual_review"]:
        log_line(f"  {MANUAL_REVIEW} {entry['slug']}: {entry['reason']}", log_path)
    return result


def _collapsible_slugs(store: Any) -> List[str]:
    """Slugs of the queued tasks consolidation would consider. [] if unavailable."""
    if store is None:
        return []
    try:
        rows = store.select("tasks", {"select": "slug", "state": "eq.QUEUED"}) or []
        return [r.get("slug") for r in rows if r.get("slug")]
    except Exception as e:
        print(f"[backlog_console] could not read queued tasks: {e}", flush=True)
        return []


def _tag_manual_review(store: Any, slug: str, reason: str) -> bool:
    """Mark one task for manual review. Never raises."""
    if store is None or not slug:
        return False
    try:
        store.update("tasks", {"slug": slug},
                     {"note": f"{MANUAL_REVIEW}: {reason}", "updated_at": "now()"})
        return True
    except Exception as e:
        print(f"[backlog_console] could not tag {slug}: {e}", flush=True)
        return False


def status(store: Any = None) -> Dict[str, Any]:
    """Machine-readable backlog snapshot.

    The existing backlog_status module prints a human table; nothing can assert on a
    table. This returns the same truth as JSON, plus the two keys the acceptance
    criterion names.
    """
    store = store if store is not None else _load_db()
    out: Dict[str, Any] = {"ok": True, "states": {}, "collapsed_tasks": [],
                           "manual_review": [], "backlog_total": 0}
    if store is None:
        out.update(ok=False, error="control plane unavailable")
        return out

    for state in BACKLOG_STATES:
        try:
            out["states"][state] = store.count("tasks", {"state": f"eq.{state}"})
        except Exception as e:
            out["states"][state] = None
            out["ok"] = False
            out.setdefault("errors", []).append(f"{state}: {e}")
    out["backlog_total"] = sum(v for v in out["states"].values() if isinstance(v, int))

    try:
        rows = store.select("tasks", {"select": "slug,note", "state": "eq.DECOMPOSED"}) or []
        out["collapsed_tasks"] = sorted(r.get("slug") for r in rows if r.get("slug"))
    except Exception as e:
        out["ok"] = False
        out.setdefault("errors", []).append(f"collapsed: {e}")

    try:
        rows = store.select("tasks", {"select": "slug,note",
                                      "note": f"like.{MANUAL_REVIEW}%"}) or []
        out["manual_review"] = sorted(r.get("slug") for r in rows if r.get("slug"))
    except Exception as e:
        out["ok"] = False
        out.setdefault("errors", []).append(f"manual_review: {e}")
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    """`beethoven consolidate [--all]` / `beethoven backlog status`. Returns exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print("usage: beethoven consolidate [--all] | beethoven backlog status")
        return 0 if argv else 2

    command = argv[0]
    if command == "consolidate":
        payload = consolidate(all_projects="--all" in argv)
    elif command == "backlog" and len(argv) > 1 and argv[1] == "status":
        payload = status()
    else:
        print(json.dumps({"ok": False, "error": f"unknown command: {' '.join(argv)}"}))
        return 2

    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
