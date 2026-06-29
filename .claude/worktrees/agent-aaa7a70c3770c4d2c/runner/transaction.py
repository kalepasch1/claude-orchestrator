#!/usr/bin/env python3
"""
transaction.py - cross-repo refactor TRANSACTIONS. A single logical change spanning multiple
repos (e.g. an API contract + every consumer) shipped all-or-nothing: each repo's branch is
prepared and tested; only if ALL pass are they integrated; if any fails, none merge.

Tasks join a transaction via a shared `txn` tag (metadata in the prompt or a txns table).
This module coordinates: it watches the member tasks, and gates integration on全member pass.
Minimal coordinator - integrate step is delegated to runner.integrate per repo.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def members(txn_id):
    # convention: member tasks carry note like 'txn:<id>'
    rows = db.select("tasks", {"select": "id,project_id,slug,state,note"}) or []
    return [r for r in rows if (r.get("note") or "").find(f"txn:{txn_id}") >= 0]


def status(txn_id):
    m = members(txn_id)
    if not m:
        return {"ready": False, "reason": "no members"}
    done = [r for r in m if r["state"] in ("DONE",)]
    failed = [r for r in m if r["state"] in ("BLOCKED", "CONFLICT", "TESTFAIL")]
    return {"members": len(m), "ready": len(done) == len(m), "failed": len(failed),
            "abort": len(failed) > 0}


# Integration policy: a scheduled coordinator calls status(); when ready -> tell runner to
# ff-merge each member branch; when abort -> mark all members BLOCKED with note 'txn aborted'.
def resolve(txn_id):
    s = status(txn_id)
    if s.get("abort"):
        for r in members(txn_id):
            db.update("tasks", {"id": r["id"]}, {"state": "BLOCKED", "note": f"txn:{txn_id} aborted (a member failed)"})
        return f"transaction {txn_id} aborted; no repo merged"
    if s.get("ready"):
        return f"transaction {txn_id} ready: integrate all {s['members']} member branches now"
    return f"transaction {txn_id} pending ({s.get('members')} members)"


if __name__ == "__main__":
    print(resolve(sys.argv[1] if len(sys.argv) > 1 else "demo"))
