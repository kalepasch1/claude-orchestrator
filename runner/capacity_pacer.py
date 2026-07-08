#!/usr/bin/env python3
"""
capacity_pacer.py — Proactive token budget pacing across accounts (500X).

Instead of burning through subscription tokens as fast as possible (→ all accounts
exhausted simultaneously → fleet idles for days), this module paces consumption
to spread it across the weekly window.

Key insight: subscription accounts have a WEEKLY token budget that resets on a
rolling basis. If we know:
  - tokens_used_this_period
  - hours_until_reset
  - tasks_queued

We can compute a sustainable claiming rate that keeps the fleet running continuously
instead of sprinting and crashing.

Usage:
    import capacity_pacer
    if capacity_pacer.should_claim():
        # ok to claim a task
    else:
        # pacing — wait for the next claim window

    capacity_pacer.record_spend(account_name, tokens_used)
"""
import os, sys, json, time, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Configuration
PACING_ENABLED = os.environ.get("ORCH_CAPACITY_PACING", "true").lower() in ("true", "1", "yes")
# Estimated weekly token budget per Max subscription account
WEEKLY_BUDGET_PER_ACCOUNT = int(os.environ.get("ORCH_WEEKLY_BUDGET_TOKENS", str(45_000_000)))
# Reserve percentage — don't consume more than this fraction per period
RESERVE_PCT = float(os.environ.get("ORCH_CAPACITY_RESERVE_PCT", "0.10"))
# Minimum claim interval when pacing (seconds between claims)
MIN_CLAIM_INTERVAL = int(os.environ.get("ORCH_MIN_CLAIM_INTERVAL", "30"))
# Hours in the reset period (rolling weekly)
RESET_PERIOD_H = int(os.environ.get("ORCH_RESET_PERIOD_H", "168"))  # 7 days


_STATE_DIR = os.path.join(os.environ.get("CLAUDE_ORCH_HOME",
    os.path.expanduser("~/.claude-orchestrator")), "module_state")


def _store():
    path = os.path.join(_STATE_DIR, "capacity_pacer.json")
    try:
        return json.load(open(path))
    except Exception:
        return {}


def _save(store):
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
        json.dump(store, open(os.path.join(_STATE_DIR, "capacity_pacer.json"), "w"), default=str)
    except Exception:
        pass


def record_spend(account_name, tokens_used, cost_usd=0):
    """Record token spend for an account in the current period."""
    if not PACING_ENABLED:
        return
    store = _store()

    key = f"spend:{account_name}"
    entry = store.get(key, {"total_tokens": 0, "total_cost": 0, "period_start": time.time(), "claims": 0})

    # Reset if period has elapsed
    period_start = entry.get("period_start", time.time())
    if time.time() - period_start > RESET_PERIOD_H * 3600:
        entry = {"total_tokens": 0, "total_cost": 0, "period_start": time.time(), "claims": 0}

    entry["total_tokens"] = entry.get("total_tokens", 0) + tokens_used
    entry["total_cost"] = entry.get("total_cost", 0) + cost_usd
    entry["claims"] = entry.get("claims", 0) + 1
    entry["last_spend"] = time.time()

    store[key] = entry
    store["last_updated"] = time.time()
    _save(store)


def _get_account_spend(account_name):
    """Get current period spend for an account."""
    store = _store()
    key = f"spend:{account_name}"
    entry = store.get(key, {})
    period_start = entry.get("period_start", time.time())
    if time.time() - period_start > RESET_PERIOD_H * 3600:
        return 0  # period has reset
    return entry.get("total_tokens", 0)


def _hours_remaining():
    """Estimate hours remaining in the current reset period."""
    store = _store()
    # Use the oldest period_start across all accounts
    starts = []
    for k, v in store.items():
        if k.startswith("spend:") and isinstance(v, dict):
            starts.append(v.get("period_start", time.time()))
    if not starts:
        return RESET_PERIOD_H
    oldest = min(starts)
    elapsed_h = (time.time() - oldest) / 3600
    remaining = max(1, RESET_PERIOD_H - elapsed_h)
    return remaining


def _total_fleet_spend():
    """Total tokens spent across all accounts this period."""
    store = _store()
    total = 0
    for k, v in store.items():
        if k.startswith("spend:") and isinstance(v, dict):
            period_start = v.get("period_start", time.time())
            if time.time() - period_start < RESET_PERIOD_H * 3600:
                total += v.get("total_tokens", 0)
    return total


def _num_accounts():
    """Count of active accounts."""
    try:
        rows = db.select("accounts", {"select": "name"})
        return len(rows or [])
    except Exception:
        return 2  # safe default


def should_claim():
    """Check if the fleet should claim a new task right now.

    Returns: {claim: bool, reason: str, utilization_pct: float, sustainable_rate: float}
    """
    if not PACING_ENABLED:
        return {"claim": True, "reason": "pacing disabled", "utilization_pct": 0}

    n_accounts = _num_accounts()
    total_budget = WEEKLY_BUDGET_PER_ACCOUNT * n_accounts
    effective_budget = total_budget * (1 - RESERVE_PCT)

    fleet_spend = _total_fleet_spend()
    hours_left = _hours_remaining()
    utilization = fleet_spend / max(total_budget, 1)

    # Sustainable rate: tokens/hour to last until reset
    sustainable_rate = (effective_budget - fleet_spend) / max(hours_left, 1)

    # If we've used > 90% of the effective budget, stop claiming
    if fleet_spend >= effective_budget:
        return {
            "claim": False,
            "reason": f"budget exhausted ({utilization:.0%} used, {hours_left:.0f}h remaining)",
            "utilization_pct": round(utilization * 100, 1),
            "sustainable_rate": 0,
        }

    # If sustainable rate is very low, throttle
    # Assume ~5000 tokens per task average
    avg_tokens_per_task = 5000
    if sustainable_rate < avg_tokens_per_task:
        return {
            "claim": False,
            "reason": f"pacing: sustainable rate too low ({sustainable_rate:.0f} tokens/h, need {avg_tokens_per_task})",
            "utilization_pct": round(utilization * 100, 1),
            "sustainable_rate": round(sustainable_rate),
        }

    # Check claim interval
    store = _store()
    last_claim = store.get("last_claim_time", 0)
    if time.time() - last_claim < MIN_CLAIM_INTERVAL:
        return {
            "claim": False,
            "reason": f"pacing: minimum interval ({MIN_CLAIM_INTERVAL}s) not elapsed",
            "utilization_pct": round(utilization * 100, 1),
            "sustainable_rate": round(sustainable_rate),
        }

    # OK to claim
    store["last_claim_time"] = time.time()
    _save(store)

    return {
        "claim": True,
        "reason": f"ok ({utilization:.0%} used, {hours_left:.0f}h left, {sustainable_rate:.0f} tokens/h)",
        "utilization_pct": round(utilization * 100, 1),
        "sustainable_rate": round(sustainable_rate),
    }


def budget_status():
    """Return fleet-wide budget status for dashboard/logging."""
    n_accounts = _num_accounts()
    total_budget = WEEKLY_BUDGET_PER_ACCOUNT * n_accounts
    fleet_spend = _total_fleet_spend()
    hours_left = _hours_remaining()
    utilization = fleet_spend / max(total_budget, 1)

    return {
        "accounts": n_accounts,
        "total_budget": total_budget,
        "spent": fleet_spend,
        "remaining": total_budget - fleet_spend,
        "utilization_pct": round(utilization * 100, 1),
        "hours_remaining": round(hours_left, 1),
        "sustainable_rate_tokens_h": round((total_budget * (1 - RESERVE_PCT) - fleet_spend) / max(hours_left, 1)),
    }


def run():
    """Periodic: report capacity pacing status."""
    status = budget_status()
    print(f"[capacity-pacer] {status['accounts']} accounts, "
          f"{status['utilization_pct']}% used, "
          f"{status['hours_remaining']}h remaining, "
          f"sustainable rate: {status['sustainable_rate_tokens_h']} tokens/h")


if __name__ == "__main__":
    run()
