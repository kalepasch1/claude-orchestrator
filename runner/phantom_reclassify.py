#!/usr/bin/env python3
"""phantom_reclassify.py — tell the truth about what actually shipped.

WHY (2026-08-04, cowork forensic audit)
---------------------------------------
13,816 tasks are marked MERGED. Using the git repos as ground truth — a commit that names
the task's slug at a token boundary, is not a placeholder, and actually changes the tree
relative to its first parent — 10,584 of them (76.6%) have no shipped code anywhere in the
target repo. They were manufactured by:

  * two bulk UPDATEs that flipped 9,068 rows to MERGED in two hours,
  * a "bulk-resolved: no branch, nothing to deploy" sweep,
  * a self-certifying recovery-stub loop,
  * quarantine_remediation marking originals MERGED whenever it requeued a copy,
  * "branch no longer exists, therefore it must have merged".

While those rows say MERGED, every throughput, merge-rate and shipped-count metric is
false, and real throughput cannot be measured at all.

WHAT THIS DOES
--------------
Moves them to PHANTOM_UNVERIFIED. NOTHING IS DELETED. Every row's prior state, prior note,
mechanism and verdict is written to `phantom_merge_audit` first, so the reclassification is
fully reversible and the reasoning stays inspectable.

The transition is authorised through bulk_update_guard's documented override
(ORCH_ALLOW_BULK_STATE_CHANGE) rather than bypassing it, so it also lands in
`bulk_state_change_audit` — the same guard that exists because of the original 9,236-row flip.

Input is the verdict file produced by the audit (task_id -> verdict/mechanism). Tasks are
re-checked at write time and only touched if they are STILL MergeD, so this cannot clobber
work that has legitimately progressed since the audit ran.

Usage:
    python3 phantom_reclassify.py --verdicts /tmp/phantom_results.json \\
                                  --mechanisms /tmp/phantom_mech.json [--apply]

Default is a dry run.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402
import bulk_update_guard  # noqa: E402

NEW_STATE = "PHANTOM_UNVERIFIED"
PHANTOM_VERDICTS = ("NO_EVIDENCE", "STUB_ONLY")
BATCH = 200
REASON = ("2026-08-04 forensic audit: reclassify tasks marked MERGED that have no shipped "
          "code in the target repo (git as ground truth). Reversible via phantom_merge_audit.")


def _post(path, body, params=None):
    return db._req("POST", path, body=body, params=params or {})


def _patch_ids(ids, patch):
    """PATCH a batch of task ids that are STILL in MERGED state."""
    params = {"id": "in.(" + ",".join(ids) + ")", "state": "eq.MERGED"}
    return db._req("PATCH", "/rest/v1/tasks", body=patch,
                   headers={"Prefer": "return=representation"}, params=params)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", default="/tmp/phantom_results.json")
    ap.add_argument("--mechanisms", default="/tmp/phantom_mech.json")
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--actor", default="cowork-phantom-audit")
    args = ap.parse_args()

    results = json.load(open(args.verdicts))
    mechs = json.load(open(args.mechanisms)) if os.path.exists(args.mechanisms) else {}

    targets = [r for r in results if r.get("verdict") in PHANTOM_VERDICTS]
    print(f"verdict file: {len(results)} MERGED tasks, {len(targets)} phantom")
    if not targets:
        return 0

    # Only touch rows that are STILL MERGED — the audit is a snapshot, and other agents are
    # active. Re-read current state rather than trusting the file.
    live = {}
    for i in range(0, len(targets), 500):
        ids = [t["id"] for t in targets[i:i + 500]]
        rows = db.select("tasks", {"select": "id,state,note",
                                   "id": "in.(" + ",".join(ids) + ")",
                                   "limit": "1000"}) or []
        for r in rows:
            live[r["id"]] = r
    still = [t for t in targets if (live.get(t["id"]) or {}).get("state") == "MERGED"]
    print(f"still MERGED right now: {len(still)} (skipping {len(targets)-len(still)} that moved)")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        by_mech = {}
        for t in still:
            by_mech[mechs.get(t["id"], "unknown")] = by_mech.get(mechs.get(t["id"], "unknown"), 0) + 1
        for k, v in sorted(by_mech.items(), key=lambda kv: -kv[1]):
            print(f"  {k:32s} {v:6d}")
        return 0

    # ---- authorise through the guard's documented override (never bypass it) ----
    if not bulk_update_guard.override_token():
        os.environ["ORCH_ALLOW_BULK_STATE_CHANGE"] = REASON
    bulk_update_guard.check("tasks", {"state": NEW_STATE}, len(still),
                            actor=args.actor, reason=REASON)

    # ---- 1. write the reversal record FIRST ----
    written = 0
    for i in range(0, len(still), BATCH):
        chunk = still[i:i + BATCH]
        rows = [{
            "task_id": t["id"],
            "slug": t.get("slug"),
            "project_name": t.get("project"),
            "prior_state": "MERGED",
            "new_state": NEW_STATE,
            "mechanism": mechs.get(t["id"], "unknown"),
            "verdict": t.get("verdict"),
            "prior_note": (live.get(t["id"], {}).get("note") or "")[:4000],
            "evidence": "no commit in target repo names this slug at a token boundary on a "
                        "non-placeholder, tree-changing commit",
            "actor": args.actor,
            "reason": REASON,
        } for t in chunk]
        _post("/rest/v1/phantom_merge_audit", rows)
        written += len(rows)
        print(f"  audit {written}/{len(still)}", flush=True)

    # ---- 2. reclassify ----
    moved = 0
    for i in range(0, len(still), BATCH):
        chunk = still[i:i + BATCH]
        note = (f"PHANTOM_UNVERIFIED (2026-08-04 audit): marked MERGED but no shipped code "
                f"found in the target repo. Prior state and note preserved in "
                f"phantom_merge_audit. Not deleted, not judged — unverified.")
        res = _patch_ids([t["id"] for t in chunk], {"state": NEW_STATE, "note": note})
        moved += len(res or [])
        print(f"  reclassified {moved}/{len(still)}", flush=True)

    print(f"\nDONE: {moved} tasks MERGED -> {NEW_STATE}; {written} reversal records written.")
    print("Nothing was deleted. Reverse with: "
          "UPDATE tasks t SET state='MERGED' FROM phantom_merge_audit a "
          "WHERE a.task_id=t.id AND t.state='PHANTOM_UNVERIFIED';")
    return 0


if __name__ == "__main__":
    sys.exit(main())
