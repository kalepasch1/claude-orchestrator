#!/usr/bin/env python3
"""Recover operator improvements that were falsely certified as merged.

The forensic audit deliberately moved evidence-free MERGED rows to
PHANTOM_UNVERIFIED.  That made the metrics truthful, but the claim loop does not
consume that state, so manual dropbox work remained permanently stranded.  This
job returns only operator-originated dropbox rows to QUEUED, one audited row at a
time, with an explicit reconcile-first/non-destructive implementation contract.
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


RECOVERY_MARK = "OPERATOR_PHANTOM_RECOVERY"
RECOVERY_CONTRACT = """## OPERATOR PHANTOM RECOVERY CONTRACT
This manual improvement was previously marked MERGED without repository evidence.
Reconcile it against the current base before editing. Preserve every newer or
overlapping improvement already present; layer in only missing optimal behavior.
If the behavior already exists, prove it with focused tests and an exact artifact
commit instead of replacing code or returning a no-op. The task is complete only
after tests, preservation/regression checks, staging integration, production
release, and deployment verification are durably recorded.
## END OPERATOR PHANTOM RECOVERY CONTRACT

"""


def _candidate_rows(limit):
    return db.select("tasks", {
        "select": "id,slug,prompt,note,state",
        "state": "eq.PHANTOM_UNVERIFIED",
        "slug": "like.dropbox-%",
        "order": "created_at.asc",
        "limit": str(max(1, int(limit))),
    }) or []


def recover(limit=100):
    rows = _candidate_rows(limit)
    recovered = []
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for row in rows:
        if row.get("state") != "PHANTOM_UNVERIFIED":
            continue
        prompt = str(row.get("prompt") or "")
        if RECOVERY_MARK not in prompt:
            prompt = f"{RECOVERY_CONTRACT}{RECOVERY_MARK}\n\n{prompt}"
        prior_note = str(row.get("note") or "")
        note = (
            f"{RECOVERY_MARK} {now}: requeued operator-originated work after false-merge audit; "
            "reconcile current code, preserve overlaps, and require exact ship evidence. "
            f"Prior note: {prior_note}"
        )[:4000]
        # Match by id and prior state so concurrent recovery can never double-claim
        # or move a row that progressed after this scan.
        result = db.update("tasks", {
            "id": row["id"], "state": "PHANTOM_UNVERIFIED",
        }, {
            "state": "QUEUED",
            "prompt": prompt,
            "note": note,
            "submitted_by": "legacy-dropbox-owner",
            "submitted_by_label": "Kale Pasch (legacy dropbox)",
            "priority": 10,
        })
        if result is not None:
            recovered.append(row.get("slug"))
    try:
        import steering
        if recovered:
            steering.record(
                "operator_phantom_recovery", project="beethoven",
                actor_label="Kale Pasch",
                rationale="Restore manual improvements stranded by evidence-free MERGED certification",
                payload={"recovered": len(recovered), "first": recovered[:20]},
            )
    except Exception:
        pass
    print(f"phantom_recovery: recovered {len(recovered)}/{len(rows)} operator task(s)")
    return {"scanned": len(rows), "recovered": len(recovered), "slugs": recovered}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=int(os.environ.get("PHANTOM_RECOVERY_LIMIT", "100")))
    args = parser.parse_args()
    recover(limit=args.limit)


if __name__ == "__main__":
    main()
