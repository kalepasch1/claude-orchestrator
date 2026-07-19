#!/usr/bin/env python3
"""
provider_rate_router.py — Proactive rate-aware routing across provider accounts.

When dispatching parallel tasks the runner's current approach is reactive:
account_pool.current() returns the first healthy account (serial round-robin) and
only rotates AFTER a limit is hit. Under parallel load this means several tasks
land on the same account simultaneously, burning capacity unevenly and triggering
avoidable rate-limit cooldowns.

This module adds a proactive pick() function that:
  1. Collects all healthy accounts and their estimated remaining capacity.
  2. Ranks them by (cooling_down=0 first, then remaining_tokens descending).
  3. Returns the best account for the next task plus a routing log entry for
     the operator audit trail.

No secrets are read or stored here. Credential injection is delegated entirely to
account_pool.env_for(), which already guards API billing consent. This module only
reads the existing cooldown state and capacity_pacer spend estimates.

Human approval gate: routing decisions are logged via routing_log(); operators
can inspect and override via ORCH_FORCE_ACCOUNT=<name> before restart.

Usage:
    import provider_rate_router as prr
    account, log_entry = prr.pick(task_slug="my-task")
    env = account_pool.pool.env_for(account) if account else {}
"""
import os
import sys
import time
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger(__name__)

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
_STATE_DIR = os.path.join(HOME, "module_state")
_ROUTING_LOG = os.path.join(_STATE_DIR, "provider_routing_log.jsonl")

# Env override: operator can pin a specific account for the next N tasks.
FORCE_ACCOUNT = os.environ.get("ORCH_FORCE_ACCOUNT", "").strip()

# Estimated tokens per task (mirrors capacity_pacer default).
_EST_TOKENS = int(os.environ.get("ORCH_EST_TOKENS_PER_TASK", "5000"))
_WEEKLY_BUDGET = int(os.environ.get("ORCH_WEEKLY_BUDGET_TOKENS", str(45_000_000)))


def _account_remaining(name: str) -> int:
    """Estimate remaining weekly tokens for account `name` from capacity_pacer state."""
    try:
        path = os.path.join(_STATE_DIR, "capacity_pacer.json")
        store = json.load(open(path))
        key = f"spend:{name}"
        entry = store.get(key, {})
        period_h = int(os.environ.get("ORCH_RESET_PERIOD_H", "168"))
        period_start = entry.get("period_start", time.time())
        if time.time() - period_start > period_h * 3600:
            return _WEEKLY_BUDGET  # period has reset
        used = entry.get("total_tokens", 0)
        return max(0, _WEEKLY_BUDGET - used)
    except Exception:
        return _WEEKLY_BUDGET  # unknown -> assume full budget


def _all_accounts():
    """Return list of (account_dict, is_healthy, cooldown_until, remaining_tokens)."""
    try:
        import account_pool as ap
        pool = ap.AccountPool()
        results = []
        for a in pool.accts:
            cd_until = pool.state.get(a["name"], {}).get("cooldown_until", 0)
            healthy = time.time() >= cd_until
            remaining = _account_remaining(a["name"])
            results.append((a, healthy, cd_until, remaining))
        return results
    except Exception as exc:
        log.warning("provider_rate_router: could not load accounts (%s)", exc)
        return []


def pick(task_slug: str = "") -> tuple:
    """Pick the best provider account for the next task.

    Returns (account_dict | None, log_entry_dict).
    account_dict is None only when every account is cooling down.
    The caller should pass the account to account_pool.pool.env_for() to get
    the subprocess environment — credential handling stays in account_pool.
    """
    # Operator override: pin a specific account (e.g. ORCH_FORCE_ACCOUNT=personal-max).
    if FORCE_ACCOUNT:
        try:
            import account_pool as ap
            pool = ap.AccountPool()
            forced = next((a for a in pool.accts if a["name"] == FORCE_ACCOUNT), None)
            if forced:
                entry = _log_entry(forced, "forced", task_slug, _account_remaining(forced["name"]))
                routing_log(entry)
                return forced, entry
        except Exception:
            pass

    accounts = _all_accounts()
    if not accounts:
        entry = _log_entry(None, "no_accounts", task_slug, 0)
        routing_log(entry)
        return None, entry

    # Sort: healthy first, then by remaining capacity descending.
    accounts.sort(key=lambda t: (0 if t[1] else 1, -t[3]))

    best_acct, healthy, cd_until, remaining = accounts[0]

    if healthy:
        reason = "healthy_max_capacity"
    else:
        # All cooling — pick the one with the soonest reset.
        accounts.sort(key=lambda t: t[2])
        best_acct, _, cd_until, remaining = accounts[0]
        reason = f"all_cooling_soonest_reset:{int(cd_until - time.time())}s"

    entry = _log_entry(best_acct, reason, task_slug, remaining)
    routing_log(entry)
    return best_acct, entry


def _log_entry(account, reason: str, task_slug: str, remaining: int) -> dict:
    return {
        "ts": time.time(),
        "task": task_slug,
        "account": account["name"] if account else None,
        "reason": reason,
        "est_remaining_tokens": remaining,
        "est_tasks_remaining": remaining // _EST_TOKENS if _EST_TOKENS else 0,
    }


def routing_log(entry: dict) -> None:
    """Append a routing decision to the operator audit log (JSONL)."""
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
        with open(_ROUTING_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def status() -> dict:
    """Return a snapshot of all accounts with health + capacity info."""
    accounts = _all_accounts()
    return {
        "accounts": [
            {
                "name": a["name"],
                "healthy": healthy,
                "cooldown_until": cd_until if not healthy else None,
                "cooldown_remaining_s": max(0, int(cd_until - time.time())) if not healthy else 0,
                "est_remaining_tokens": remaining,
                "est_tasks_remaining": remaining // _EST_TOKENS if _EST_TOKENS else 0,
            }
            for a, healthy, cd_until, remaining in accounts
        ],
        "recommended": pick.__doc__.split("\n")[0],
    }


if __name__ == "__main__":
    import json as _json
    acct, log_e = pick(task_slug="cli-test")
    print(_json.dumps({"picked": acct, "log": log_e}, indent=2))
