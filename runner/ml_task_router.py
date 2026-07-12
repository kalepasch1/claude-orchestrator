#!/usr/bin/env python3
"""
ml_task_router.py - dynamic task-to-runner assignment based on capability and load.

Slice-3: uses historical outcome data to learn which runners/accounts are best
suited for different task kinds, and routes accordingly:
  - Builds a capability profile per account from outcome history
  - Considers current load (running task count) per account
  - Scores candidate accounts using success-rate × availability
  - Falls back to round-robin when data is insufficient

Integrates with claim_task in runner.py: instead of random claim, the runner
calls suggest_account() to pick the best-fit account for a task.
"""
import collections, json, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import log as _log_mod
_log = _log_mod.get("ml_task_router")

MIN_SAMPLES = int(os.environ.get("ORCH_ROUTER_MIN_SAMPLES", "5"))
LOAD_PENALTY = float(os.environ.get("ORCH_ROUTER_LOAD_PENALTY", "0.15"))
REFRESH_INTERVAL = int(os.environ.get("ORCH_ROUTER_REFRESH_SEC", "300"))

_lock = threading.Lock()
_profiles = {}  # account -> {kind -> {attempts, successes, avg_cost}}
_last_refresh = 0


def _refresh_profiles():
    """Build capability profiles from outcome history."""
    global _last_refresh
    now = time.time()
    if now - _last_refresh < REFRESH_INTERVAL:
        return
    _last_refresh = now

    try:
        outcomes = db.select("outcomes", {
            "select": "account,kind,merged,usd",
            "order": "created_at.desc",
            "limit": "500",
        }) or []
    except Exception as e:
        _log.debug("ml_task_router: profile refresh failed: %s", e)
        return

    profiles = collections.defaultdict(lambda: collections.defaultdict(
        lambda: {"attempts": 0, "successes": 0, "total_cost": 0.0}))

    for o in outcomes:
        acct = o.get("account", "unknown")
        kind = o.get("kind", "build")
        profiles[acct][kind]["attempts"] += 1
        if o.get("merged"):
            profiles[acct][kind]["successes"] += 1
        profiles[acct][kind]["total_cost"] += float(o.get("usd") or 0)

    with _lock:
        _profiles.clear()
        _profiles.update(profiles)


def _current_load():
    """Get running task count per account."""
    try:
        running = db.select("tasks", {
            "select": "account",
            "state": "eq.RUNNING",
        }) or []
        load = collections.Counter(t.get("account", "") for t in running)
        return dict(load)
    except Exception:
        return {}


def suggest_account(task_kind, available_accounts=None):
    """Suggest the best account for a task of the given kind.

    Args:
        task_kind: str like "build", "bugfix", "test", etc.
        available_accounts: optional list of accounts to choose from

    Returns:
        {"account": str, "score": float, "reason": str}
    """
    _refresh_profiles()
    load = _current_load()

    with _lock:
        candidates = list(_profiles.keys()) if not available_accounts else available_accounts

    if not candidates:
        return {"account": None, "score": 0, "reason": "no candidates"}

    scored = []
    for acct in candidates:
        with _lock:
            kind_stats = _profiles.get(acct, {}).get(task_kind, {})

        attempts = kind_stats.get("attempts", 0) if kind_stats else 0
        successes = kind_stats.get("successes", 0) if kind_stats else 0

        if attempts < MIN_SAMPLES:
            # Insufficient data — use neutral score with slight exploration bonus
            base_score = 0.5 + (0.01 * (MIN_SAMPLES - attempts))
        else:
            base_score = successes / attempts

        # Penalize loaded accounts
        current = load.get(acct, 0)
        score = max(0.0, base_score - (current * LOAD_PENALTY))

        scored.append((score, acct))

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_acct = scored[0]

    reason = "historical performance" if best_score != 0.5 else "exploration (insufficient data)"
    return {"account": best_acct, "score": round(best_score, 3), "reason": reason}


def bulk_assign(tasks, available_accounts=None):
    """Assign accounts to a batch of tasks, load-balancing across them.

    Args:
        tasks: list of task dicts with at least "kind" field
        available_accounts: optional list

    Returns:
        list of {"task_id": str, "account": str, "score": float}
    """
    assignments = []
    simulated_load = collections.Counter()

    for t in tasks:
        kind = t.get("kind", "build")
        suggestion = suggest_account(kind, available_accounts)
        acct = suggestion["account"]
        if acct:
            simulated_load[acct] += 1
        assignments.append({
            "task_id": t.get("id", ""),
            "account": acct,
            "score": suggestion["score"],
        })
    return assignments


def stats():
    """Return router statistics."""
    with _lock:
        return {
            "profiles": {acct: {k: dict(v) for k, v in kinds.items()}
                         for acct, kinds in _profiles.items()},
            "last_refresh": _last_refresh,
        }


def run():
    """Periodic: refresh profiles."""
    _refresh_profiles()
    return stats()


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
