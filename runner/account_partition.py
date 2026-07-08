#!/usr/bin/env python3
"""
account_partition.py — Cross-machine account affinity (100X).

Prevents both Macs from burning the same account simultaneously by assigning
primary/secondary account affinity per machine. Each machine preferentially
uses its primary account, only failing over to others when primary is exhausted.

This halves per-account burn rate and makes capacity pacing much simpler.

Schema: uses the existing `machine` column in the `accounts` table.
If machine=NULL, account is shared (any Mac can use it).
If machine=hostname, only that Mac uses it as primary.

Usage:
    import account_partition
    account_partition.auto_partition()  # assigns accounts to machines
    # AccountPool._load_cfg() already respects the machine column
"""
import os, sys, json, time, socket
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

PARTITION_ENABLED = os.environ.get("ORCH_ACCOUNT_PARTITION", "true").lower() in ("true", "1", "yes")


def _get_fleet_machines():
    """Get all known machines from runner_heartbeats.

    Uses the 'hostname' column which is the human-readable machine name,
    NOT runner_id which has pid/lane suffixes that break affinity matching.
    Falls back to runner_id prefix extraction if hostname column is missing.
    """
    try:
        rows = db.select("runner_heartbeats", {"select": "runner_id,hostname", "order": "last_seen.desc", "limit": "20"})
        machines = set()
        for r in (rows or []):
            # Prefer hostname column (clean machine name like "Mac.lan lane 8")
            h = r.get("hostname", "")
            if h:
                # Extract base hostname (strip " lane N" suffix)
                base = h.split(" lane")[0].split("-lane")[0].strip()
                if base:
                    machines.add(base)
                    continue
            # Fallback: extract from runner_id (hostname-pid-lane-N)
            rid = r.get("runner_id", "")
            if rid:
                # Take everything before the first numeric segment
                parts = rid.split("-")
                base = parts[0] if parts else rid
                machines.add(base)
        return sorted(machines)
    except Exception:
        return [socket.gethostname()]


def _get_accounts():
    """Get all accounts from DB."""
    try:
        return db.select("accounts", {"select": "name,machine,priority", "order": "priority.asc"}) or []
    except Exception:
        return []


def auto_partition():
    """Auto-assign accounts to machines using round-robin.

    Only partitions accounts that have machine=NULL (unassigned).
    If there are more accounts than machines, extras stay shared (NULL).

    Returns: list of {account, machine, action} describing what was done.
    """
    if not PARTITION_ENABLED:
        return [{"action": "skipped", "reason": "partitioning disabled"}]

    machines = _get_fleet_machines()
    accounts = _get_accounts()

    if len(machines) < 2:
        return [{"action": "skipped", "reason": f"only {len(machines)} machine(s) — partitioning needs 2+"}]

    unassigned = [a for a in accounts if not a.get("machine")]
    if not unassigned:
        return [{"action": "skipped", "reason": "all accounts already assigned"}]

    results = []
    for i, acct in enumerate(unassigned):
        if i < len(machines):
            # Assign this account to a specific machine
            machine = machines[i % len(machines)]
            try:
                db.update("accounts", {"name": acct["name"]}, {"machine": machine})
                results.append({"account": acct["name"], "machine": machine, "action": "assigned"})
            except Exception as e:
                results.append({"account": acct["name"], "action": "failed", "error": str(e)[:100]})
        else:
            # More accounts than machines — keep shared
            results.append({"account": acct["name"], "machine": None, "action": "shared (overflow)"})

    return results


def current_partition():
    """Show current partition state."""
    accounts = _get_accounts()
    hostname = socket.gethostname()
    return {
        "hostname": hostname,
        "accounts": [{"name": a["name"], "machine": a.get("machine"), "is_mine": not a.get("machine") or a["machine"] == hostname}
                     for a in accounts],
    }


def ensure_partition():
    """Check partition, auto-assign if needed, return status."""
    accounts = _get_accounts()
    unassigned = [a for a in accounts if not a.get("machine")]
    if unassigned and len(_get_fleet_machines()) >= 2:
        auto_partition()
    return current_partition()


def run():
    """Periodic: check and report partition status."""
    if not PARTITION_ENABLED:
        print("[partition] disabled")
        return

    status = current_partition()
    mine = [a["name"] for a in status["accounts"] if a.get("is_mine")]
    print(f"[partition] {status['hostname']}: {len(mine)} usable accounts: {', '.join(mine)}")

    # Auto-partition if we detect multiple machines but no partitioning
    accounts = _get_accounts()
    unassigned = [a for a in accounts if not a.get("machine")]
    machines = _get_fleet_machines()
    if unassigned and len(machines) >= 2:
        results = auto_partition()
        for r in results:
            print(f"[partition] {r.get('action')}: {r.get('account', '')} -> {r.get('machine', '')}")


if __name__ == "__main__":
    run()
