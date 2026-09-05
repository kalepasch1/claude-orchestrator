#!/usr/bin/env python3
"""
conflict_auto_resolve.py - automated conflict resolution with historical learning.

Slice-3: builds on conflict_predictor.py to add:
  - Historical conflict outcome tracking (which resolutions worked)
  - Automatic resolution selection based on past success rates
  - Approval workflow integration: auto-approve low-risk resolutions,
    queue high-risk ones for human review
  - Conflict pattern clustering for smarter prediction

Uses outcome data from the `outcomes` table to learn which resolution
strategies (rebase, re-slice, serialize) work best for each conflict type.
"""
import collections, json, os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import log as _log_mod
_log = _log_mod.get("conflict_auto_resolve")

AUTO_RESOLVE_CONFIDENCE = float(os.environ.get("ORCH_CONFLICT_AUTO_RESOLVE_CONF", "0.75"))
MAX_AUTO_RESOLVES_PER_HOUR = int(os.environ.get("ORCH_CONFLICT_AUTO_MAX_HOUR", "10"))

_lock = threading.Lock()
_resolution_log = []  # recent auto-resolutions for rate limiting
_strategy_scores = collections.defaultdict(lambda: {"attempts": 0, "successes": 0})

# Resolution strategies ordered by risk (lowest first)
STRATEGIES = [
    {"name": "rebase_fresh", "risk": 0.1,
     "description": "Rebase task branch on latest base; works for non-overlapping changes"},
    {"name": "serialize", "risk": 0.2,
     "description": "Defer task until conflicting task merges; safest but slower"},
    {"name": "reslice", "risk": 0.4,
     "description": "Re-decompose overlapping tasks into non-conflicting slices"},
    {"name": "manual_merge", "risk": 0.8,
     "description": "Queue for human review with conflict diff attached"},
]


def _load_historical_outcomes():
    """Load past conflict resolution outcomes from DB."""
    try:
        rows = db.select("outcomes", {
            "select": "slug,kind,merged,error",
            "order": "created_at.desc",
            "limit": "200",
        }) or []
        for r in rows:
            slug = r.get("slug", "")
            if "conflict" in slug or "rebase" in slug:
                strategy = "rebase_fresh" if "rebase" in slug else "serialize"
                _strategy_scores[strategy]["attempts"] += 1
                if r.get("merged"):
                    _strategy_scores[strategy]["successes"] += 1
    except Exception as e:
        _log.debug("conflict_auto_resolve: historical load failed: %s", e)


def _score_strategy(strategy_name, file_overlap_ratio):
    """Score a resolution strategy based on historical success + overlap severity."""
    s = _strategy_scores.get(strategy_name, {"attempts": 0, "successes": 0})
    if s["attempts"] < 3:
        return 0.5  # insufficient data, neutral score
    base = s["successes"] / s["attempts"]
    # Penalize aggressive strategies when overlap is high
    risk = next((st["risk"] for st in STRATEGIES if st["name"] == strategy_name), 0.5)
    penalty = risk * file_overlap_ratio
    return max(0.0, min(1.0, base - penalty))


#: Paths that are regenerated, machine-written or pure scratch. A conflict confined to
#: these is never a disagreement about the work — it is two agents' noise colliding.
#: Matched on the basename and on the full path, case-insensitively.
DISPOSABLE_PATTERNS = (
    ".aider", ".ds_store", ".orig", ".rej", ".pyc", ".log",
    "__pycache__/", "node_modules/", ".nuxt/", ".next/", "dist/", "build/",
    ".pytest_cache/", ".coverage",
)

#: Generated but meaningful: regenerating beats hand-merging, yet dropping a side is not
#: safe, so these downgrade the strategy without being treated as pure noise.
REGENERABLE_PATTERNS = (
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "requirements.lock", "database.types.ts",
)


def classify_conflict_files(files):
    """Split conflicting paths into disposable / regenerable / source.

    Returns ``{"disposable": [...], "regenerable": [...], "source": [...]}``.
    Never raises: unparseable input yields three empty lists.
    """
    result = {"disposable": [], "regenerable": [], "source": []}
    try:
        if isinstance(files, str):
            candidates = files.replace(",", "\n").split("\n")
        else:
            candidates = list(files or [])
    except Exception:
        return result

    for item in candidates:
        try:
            path = str(item).strip()
        except Exception:
            continue
        if not path:
            continue
        lowered = path.lower()
        base = lowered.rsplit("/", 1)[-1]
        if any(p in lowered or base.startswith(p) or base.endswith(p)
               for p in DISPOSABLE_PATTERNS):
            result["disposable"].append(path)
        elif any(base == p for p in REGENERABLE_PATTERNS):
            result["regenerable"].append(path)
        else:
            result["source"].append(path)
    return result


def triage_conflict_files(files):
    """Recommend a strategy from the *kind* of files in conflict, or None.

    A rebase-and-rebuild redo is the fleet's default answer to any conflict, and for a
    conflict that is entirely scratch or entirely lockfile it is the wrong one: the redo
    reproduces exactly the same collision, so the cap burns through and the branch ends
    up parked with "needs manual rebase". The operator note behind this task records four
    redos spent on conflicts that came from tracked .aider.* scratch files.

    Returns a resolution dict (same shape as recommend_resolution) or None when the
    conflict involves real source and the scored strategies should decide.
    """
    classified = classify_conflict_files(files)
    if not any(classified.values()):
        return None
    if classified["source"]:
        return None

    if classified["disposable"] and not classified["regenerable"]:
        names = ", ".join(classified["disposable"][:5])
        return {
            "strategy": "rebase_fresh",
            "confidence": 0.95,
            "auto_approve": True,
            "reason": (f"conflict is only in disposable/scratch paths ({names}); "
                       "untrack or gitignore them — a redo reproduces the same collision"),
            "file_classes": classified,
            "alternatives": [],
        }

    names = ", ".join(classified["regenerable"][:5])
    return {
        "strategy": "rebase_fresh",
        "confidence": 0.8,
        "auto_approve": False,
        "reason": (f"conflict is only in regenerable artifacts ({names}); take the base "
                   "version and regenerate rather than hand-merging"),
        "file_classes": classified,
        "alternatives": [],
    }


def _conflict_files(conflict_info):
    """Best-effort union of file paths named by a conflict_predictor payload."""
    files = []
    try:
        for conflict in conflict_info.get("conflicts") or []:
            for key in ("files", "overlapping_files", "paths"):
                value = conflict.get(key)
                if isinstance(value, str):
                    files.append(value)
                elif value:
                    files.extend(str(v) for v in value)
    except Exception:
        return []
    return files


def recommend_resolution(conflict_info):
    """Given conflict_predictor output, recommend a resolution strategy.

    Args:
        conflict_info: dict from conflict_predictor.check_conflicts()

    Returns:
        {"strategy": str, "confidence": float, "auto_approve": bool, "reason": str}
    """
    if not conflict_info or conflict_info.get("action") == "proceed":
        return {"strategy": "none", "confidence": 1.0, "auto_approve": True,
                "reason": "no conflict detected"}

    # Drop malformed rows rather than letting one None entry raise AttributeError out of
    # the overlap calculation below — this is called on the merge path, where a crash
    # turns a recoverable conflict into a wedged card.
    conflicts = [c for c in (conflict_info.get("conflicts") or []) if isinstance(c, dict)]
    if not conflicts:
        return {"strategy": "none", "confidence": 1.0, "auto_approve": True,
                "reason": "empty conflict list"}

    # File-class triage first. Historical scores are learned across ALL conflicts, so a
    # conflict confined to scratch or lockfiles gets the fleet's average answer — a redo,
    # which reproduces the identical collision. When the file classes settle the question,
    # they beat the average; rate limiting below still applies to the auto-approval.
    triaged = triage_conflict_files(_conflict_files(conflict_info))
    if triaged:
        if triaged.get("auto_approve"):
            with _lock:
                cutoff = time.time() - 3600
                _resolution_log[:] = [t for t in _resolution_log if t > cutoff]
                if len(_resolution_log) >= MAX_AUTO_RESOLVES_PER_HOUR:
                    triaged["auto_approve"] = False
                else:
                    _resolution_log.append(time.time())
        return triaged

    # Calculate file overlap ratio
    overlap = max(c.get("overlap", 0) for c in conflicts) if conflicts else 0

    # Score each strategy
    scored = []
    for st in STRATEGIES:
        score = _score_strategy(st["name"], overlap)
        scored.append((score, st))
    scored.sort(key=lambda x: x[0], reverse=True)

    best_score, best = scored[0]
    auto_approve = (best_score >= AUTO_RESOLVE_CONFIDENCE and best["risk"] <= 0.3)

    # Rate limit auto-approvals
    with _lock:
        cutoff = time.time() - 3600
        _resolution_log[:] = [t for t in _resolution_log if t > cutoff]
        if len(_resolution_log) >= MAX_AUTO_RESOLVES_PER_HOUR:
            auto_approve = False

        if auto_approve:
            _resolution_log.append(time.time())

    return {
        "strategy": best["name"],
        "confidence": round(best_score, 3),
        "auto_approve": auto_approve,
        "reason": best["description"],
        "alternatives": [{"strategy": s["name"], "score": round(sc, 3)}
                         for sc, s in scored[1:3]],
    }


def apply_resolution(task, resolution):
    """Apply a resolution strategy to a conflicting task.

    Returns True if applied, False if deferred to human review.
    """
    strategy = resolution.get("strategy", "manual_merge")
    task_id = task.get("id") if isinstance(task, dict) else task

    if not resolution.get("auto_approve"):
        # Queue for human approval
        try:
            db.insert("approvals", {
                "project": task.get("project_id", "") if isinstance(task, dict) else "",
                "kind": "conflict_resolution",
                "title": f"Conflict resolution: {strategy}",
                "why": resolution.get("reason", ""),
                "value": json.dumps(resolution),
                "risk": f"confidence={resolution.get('confidence', 0)}",
                "command": "",
            })
        except Exception as e:
            _log.warning("conflict_auto_resolve: approval insert failed: %s", e)
        return False

    # Auto-apply low-risk resolution
    if strategy == "serialize":
        try:
            db.update("tasks", {"id": task_id},
                      {"state": "QUEUED", "note": "auto-deferred: waiting for conflict to clear"})
        except Exception:
            pass
    elif strategy == "rebase_fresh":
        try:
            db.update("tasks", {"id": task_id},
                      {"state": "QUEUED", "note": "auto-requeued: rebase on fresh base"})
        except Exception:
            pass

    _log.info("conflict_auto_resolve: applied %s to task %s (conf=%.2f)",
              strategy, task_id, resolution.get("confidence", 0))
    return True


def stats():
    """Return resolution statistics."""
    return {
        "strategy_scores": dict(_strategy_scores),
        "recent_auto_resolves": len(_resolution_log),
    }


def run():
    """Periodic: load historical data and refresh strategy scores."""
    _load_historical_outcomes()
    return stats()


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
