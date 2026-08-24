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

#: Master switch for attempt_auto_rebase. OFF by default: it runs `git checkout` inside
#: the PRIMARY checkout, which is the highest-blast-radius thing this module can do.
ENABLED = os.environ.get("ORCH_CONFLICT_AUTO_REBASE_ENABLED", "false").lower() in (
    "true", "1", "yes")

#: Seconds any single git invocation may take before it is abandoned.
GIT_TIMEOUT = int(os.environ.get("ORCH_CONFLICT_GIT_TIMEOUT", "60") or 60)

#: Module logger under the name the tests patch.
log = _log

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


def _git(*args, cwd=None, timeout=GIT_TIMEOUT):
    """Run one git command. Returns (returncode, stdout-stripped). Never raises on a
    non-zero exit — a failed git call is an answer, not an exception."""
    import subprocess

    proc = subprocess.run(("git",) + tuple(args), cwd=cwd, capture_output=True,
                          text=True, timeout=timeout)
    return proc.returncode, (proc.stdout or "").strip()


def attempt_auto_rebase(branch, base, repo):
    """Rebase *branch* onto *base* inside *repo*, and put the checkout back. Returns bool.

    THE CONTRACT IS THE RESTORATION, not the rebase. This runs against
    projects.repo_path — the PRIMARY checkout, not a worktree. The earlier behaviour
    checked out the agent branch and never came back, which left the primary tree parked
    on an agent branch (1001 checkout-drift events by 2026-07-16). That is load-bearing
    drift: while parked, the repo runs THAT branch's code and honours THAT branch's
    .gitignore, so fixes committed to master go inert exactly when they are needed. It is
    the upstream cause of the intake-drop losses.

    So every exit path restores:

      * success           -> back to the original branch
      * rebase failure    -> `rebase --abort`, then back
      * an exception      -> the finally block still issues the restoring checkout, and
                             the exception propagates (a crash here must be visible, but
                             it must not stand the tree up on the wrong branch)
      * detached HEAD     -> refuse entirely. With no branch name to return to, the
                             restoration cannot be promised, and a promise that cannot be
                             kept is worse than declining the work. NO git command runs.
      * checkout failed   -> nothing moved, so there is nothing to restore
    """
    if not ENABLED:
        log.info("auto-rebase disabled (ORCH_CONFLICT_AUTO_REBASE_ENABLED)")
        return False
    if not repo or not os.path.isdir(repo):
        log.warning("auto-rebase: repo path %r is not a directory", repo)
        return False
    if not branch or not base:
        log.warning("auto-rebase: branch and base are both required")
        return False

    rc, original = _git("branch", "--show-current", cwd=repo)
    original = (original or "").strip()
    if rc != 0 or not original:
        # Detached HEAD (or git could not answer). Decline before touching anything.
        log.warning("auto-rebase: cannot read current branch in %s; refusing to move it", repo)
        return False

    rc, _ = _git("checkout", branch, cwd=repo)
    if rc != 0:
        log.warning("auto-rebase: could not check out %s; nothing moved", branch)
        return False

    try:
        rc, out = _git("rebase", base, cwd=repo)
        if rc == 0:
            log.info("auto-rebase: %s rebased onto %s", branch, base)
            return True
        log.warning("auto-rebase: %s onto %s failed (%s); aborting", branch, base,
                    (out or "").splitlines()[0] if out else "no output")
        _git("rebase", "--abort", cwd=repo)
        return False
    finally:
        # Unconditional. This is the whole point of the function.
        restore_rc, _ = _git("checkout", original, cwd=repo)
        if restore_rc != 0:
            log.error("auto-rebase: FAILED to restore %s to %s — checkout is drifted",
                      repo, original)


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

    conflicts = conflict_info.get("conflicts", [])
    if not conflicts:
        return {"strategy": "none", "confidence": 1.0, "auto_approve": True,
                "reason": "empty conflict list"}

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
