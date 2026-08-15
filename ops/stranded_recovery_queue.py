#!/usr/bin/env python3
"""Requeue stranded-branch work, one individually-provenanced insert at a time.

Deliberately NOT a sweep. A 229-branch bulk pass is the exact shape of
M4_bulk_resolved_sweep, which manufactured 3,765 phantom merges. Every entry
here is a single insert carrying its own note naming the branch it came from,
and the batch size is capped so a human checkpoint sits between passes.

What this does NOT do:
  * merge anything to master
  * bypass the merge train, QA, or the release train
  * mark anything MERGED
  * invent a task row for a branch that no longer has one
"""
import argparse
import json
import sys

# States meaning "the pipeline will never look at this again". A stranded branch
# whose task sits in one of these is genuinely abandoned.
#
# MERGED is in this list on purpose and is the important case: the task claims it
# merged, but the branch is not an ancestor of master. That is a live phantom
# merge — nothing will ever pick it up, because everything downstream believes it
# is already done.
DEAD_END_STATES = {"MERGED", "QUARANTINED", "SUPERSEDED", "TESTFAIL", "FAILED",
                   "BLOCKED", "PHANTOM_UNVERIFIED"}

# States that are still moving. Requeuing these would duplicate live work — the
# scan-window fix (7ec2d4e) restored the merge train's visibility, so DONE tasks
# holding a valid card now drain on their own.
IN_FLIGHT_STATES = {"QUEUED", "RUNNING", "DONE", "DECOMPOSED"}

RECOVERED_SUFFIX = "-recovered"
DEFAULT_BATCH = 25


def recovery_candidates(rows, task_states, batch=DEFAULT_BATCH):
    """Pick the clean, dead-ended branches worth requeuing. Ordered by value."""
    out = []
    for row in rows:
        if not row.get("clean_merge"):
            continue
        state = task_states.get(row["slug"])
        if state is None:
            # Inventory it, do not invent a task for it.
            continue
        if state in IN_FLIGHT_STATES:
            continue
        if state not in DEAD_END_STATES:
            continue
        out.append({
            "slug": row["slug"],
            "recovered_slug": row["slug"][:180] + RECOVERED_SUFFIX,
            "branch": row["branch"],
            "prior_state": state,
            "age_days": row.get("age_days"),
            "source_added": row.get("source_added"),
            "source_files": row.get("source_files"),
            # A phantom merge is the highest-value recovery: real code, and a
            # state that guarantees nothing will ever look at it again.
            "priority": 0 if state == "MERGED" else 1,
        })
    out.sort(key=lambda r: (r["priority"], -(r["source_added"] or 0)))
    return out[:batch]


def provenance_note(candidate):
    return (
        f"stranded-branch recovery 2026-08-06: re-queued from {candidate['branch']}, "
        f"which carries committed, pushed code ({candidate['source_added']} source lines "
        f"across {candidate['source_files']} files, {candidate['age_days']}d old) that is "
        f"NOT an ancestor of master. Prior task state was {candidate['prior_state']}"
        + (" — a live phantom merge: the task claimed MERGED while master never received "
           "the commit, so nothing downstream would ever look at it again."
           if candidate["prior_state"] == "MERGED" else
           " — a terminal state nothing re-examines.")
        + " Root cause is the merge-train scan-window starvation fixed in 7ec2d4e. "
          "Re-entering the NORMAL pipeline: this is not a direct merge and does not "
          "bypass the merge train, QA, or the release train."
    )


def classify_conflicting(row):
    """(a) superseded, (b) still wanted, (c) unclear. Ambiguity -> unclear."""
    if row.get("source_files", 0) == 0 and row.get("source_added", 0) == 0:
        return "superseded", "no source-file delta remains against master"
    return "unclear", ("conflicts and still carries source changes; "
                       "needs operator judgement")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", required=True, help="JSON from stranded_branch_inventory.py")
    ap.add_argument("--task-states", required=True, help="JSON map slug -> state")
    ap.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    args = ap.parse_args()

    inv = json.load(open(args.inventory))
    states = json.load(open(args.task_states))
    picks = recovery_candidates(inv["rows"], states, batch=args.batch)
    for p in picks:
        p["note"] = provenance_note(p)
    print(json.dumps({"batch_size": len(picks), "candidates": picks}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
