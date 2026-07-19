#!/usr/bin/env python3
"""
exhaustion_signal.py — Surface account exhaustion state to dashboard (10X).

When all accounts are exhausted, the dashboard shows "0 active" with no
explanation. This module writes exhaustion state to the DB so the dashboard
can display "All accounts exhausted — resets in Xh" instead of looking broken.

Reads the local claude_exhausted.json flag + account_pool state and writes
a summary to the runner_heartbeats / controls table.

Usage:
    import exhaustion_signal
    exhaustion_signal.update()  # called from scheduler
"""
import os, sys, json, time, socket
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
EXHAUSTED_FLAG = os.path.join(HOME, "claude_exhausted.json")
STATE_FILE = os.path.join(HOME, "accounts_state.json")
_STATE_DIR = os.path.join(HOME, "module_state")


def _usable_account_rows():
    """Return accounts that can actually supply Claude capacity."""
    rows = db.select("accounts", {"select": "name,type,cooldown_until"}) or []
    try:
        import account_pool
        api_allowed = account_pool._api_billing_allowed()
    except Exception:
        api_allowed = os.environ.get("ORCH_ALLOW_API_BILLING", "false").lower() == "true"
    return [r for r in rows if r.get("type") != "api" or api_allowed]


def _read_local_state():
    """Read local exhaustion state."""
    exhausted = False
    exhausted_until = 0
    accounts_cooling = []

    # Check exhaustion flag
    try:
        d = json.load(open(EXHAUSTED_FLAG))
        until = float(d.get("until", 0))
        if time.time() < until:
            exhausted = True
            exhausted_until = until
    except Exception:
        pass

    # Check per-account cooldowns
    try:
        state = json.load(open(STATE_FILE))
        for name, info in state.items():
            if isinstance(info, dict):
                cd_until = info.get("cooldown_until", 0)
                if cd_until and time.time() < cd_until:
                    accounts_cooling.append({
                        "name": name,
                        "until": cd_until,
                        "remaining_min": round((cd_until - time.time()) / 60),
                    })
    except Exception:
        pass

    return {
        "all_exhausted": exhausted or len(accounts_cooling) > 0,
        "exhausted_until": exhausted_until,
        "accounts_cooling": accounts_cooling,
        "total_cooling": len(accounts_cooling),
    }


def _read_account_cooldowns(rows=None):
    """Read account cooldowns from DB."""
    try:
        rows = _usable_account_rows() if rows is None else rows
        cooling = []
        for r in rows:
            cd = r.get("cooldown_until")
            if cd:
                # Parse ISO timestamp or unix timestamp
                try:
                    if isinstance(cd, str):
                        from datetime import datetime
                        dt = datetime.fromisoformat(cd.replace("Z", "+00:00"))
                        cd_ts = dt.timestamp()
                    else:
                        cd_ts = float(cd)
                    if time.time() < cd_ts:
                        cooling.append({
                            "name": r["name"],
                            "until": cd_ts,
                            "remaining_min": round((cd_ts - time.time()) / 60),
                        })
                except Exception:
                    pass
        return cooling
    except Exception:
        return []


def update():
    """Update exhaustion signal in DB for dashboard visibility."""
    local = _read_local_state()
    try:
        account_rows = _usable_account_rows()
    except Exception:
        account_rows = []
    usable_names = {r.get("name") for r in account_rows}
    db_cooling = _read_account_cooldowns(account_rows)

    # Merge local + DB state
    # Local state can retain disabled API rows; keep only accounts that the
    # billing guard permits when DB configuration is available.
    local_cooling = [c for c in local["accounts_cooling"]
                     if not usable_names or c.get("name") in usable_names]
    all_cooling = local_cooling + db_cooling
    # Deduplicate by name
    seen = set()
    unique_cooling = []
    for c in all_cooling:
        if c["name"] not in seen:
            seen.add(c["name"])
            unique_cooling.append(c)

    # Count total accounts
    total_accounts = len(account_rows) if account_rows else 2

    all_exhausted = len(unique_cooling) >= total_accounts and total_accounts > 0

    # Calculate earliest reset
    earliest_reset = 0
    if unique_cooling:
        earliest_reset = min(c["until"] for c in unique_cooling)

    signal = {
        "runner_id": socket.gethostname(),
        "all_exhausted": all_exhausted,
        "accounts_cooling": len(unique_cooling),
        "total_accounts": total_accounts,
        "earliest_reset_min": round((earliest_reset - time.time()) / 60) if earliest_reset > time.time() else 0,
        "details": unique_cooling[:5],
        "timestamp": time.time(),
    }

    # Write to local file for dashboard/module consumption
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
        json.dump(signal, open(os.path.join(_STATE_DIR, "exhaustion_signal.json"), "w"), default=str)
    except Exception:
        pass

    return signal


def is_fleet_exhausted():
    """Quick check: is the entire fleet exhausted?"""
    try:
        d = json.load(open(os.path.join(_STATE_DIR, "exhaustion_signal.json")))
        if time.time() - d.get("timestamp", 0) > 600:
            return False
        return d.get("all_exhausted", False)
    except Exception:
        pass
    return False


def run():
    """Periodic: update exhaustion signal."""
    signal = update()
    if signal["all_exhausted"]:
        print(f"[exhaustion] ALL EXHAUSTED — {signal['accounts_cooling']}/{signal['total_accounts']} "
              f"accounts cooling, earliest reset in {signal['earliest_reset_min']}min")
    else:
        print(f"[exhaustion] {signal['total_accounts'] - signal['accounts_cooling']}/{signal['total_accounts']} "
              f"accounts healthy")


if __name__ == "__main__":
    run()
