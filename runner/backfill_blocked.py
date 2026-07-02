#!/usr/bin/env python3
"""
backfill_blocked.py — re-queue BLOCKED tasks so they flow through the new
judge + auto-merge policy.

These tasks already passed tests at least once; the old blanket confidence gate
parked them. The new policy will judge them, auto-merge clean work, and gate
only items with genuine legal exposure.

Safety defaults:
  - Dry-run by default (no DB writes).
  - Batches of --batch-size (default 20) with a --delay-seconds pause between
    batches so the runner can work through each batch before the next lands.
  - --project <name> filters to a single project (useful for the `tomorrow` proof run).

Run on the runner Mac (SUPABASE_URL + SUPABASE_SERVICE_KEY in runner/.env):
    python3 runner/backfill_blocked.py                          # dry-run
    python3 runner/backfill_blocked.py --project tomorrow       # scope to tomorrow only
    python3 runner/backfill_blocked.py --commit                 # re-queue all blocked
    python3 runner/backfill_blocked.py --commit --project tomorrow --batch-size 10
"""
import os, sys, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

SKIP_KINDS = {"replay", "speculative"}  # these need manual re-creation; don't auto-requeue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--project", default="", help="limit to a single project name")
    ap.add_argument("--batch-size", type=int, default=20, help="tasks per batch (default 20)")
    ap.add_argument("--delay-seconds", type=float, default=30.0,
                    help="pause between batches in seconds (default 30)")
    ap.add_argument("--limit", type=int, default=0,
                    help="max tasks to re-queue total (0 = no limit)")
    args = ap.parse_args()

    params = {"select": "*", "state": "eq.BLOCKED", "order": "created_at.asc"}
    if args.project:
        # look up project id first
        projs = db.select("projects", {"select": "id,name", "name": f"eq.{args.project}"}) or []
        if not projs:
            print(f"Project '{args.project}' not found in DB.")
            sys.exit(1)
        pid = projs[0]["id"]
        params["project_id"] = f"eq.{pid}"

    rows = db.select("tasks", params) or []
    eligible = [r for r in rows if r.get("kind") not in SKIP_KINDS]

    if args.limit:
        eligible = eligible[: args.limit]

    print(f"BLOCKED tasks found: {len(rows)}  eligible for requeue: {len(eligible)}"
          + (f"  (filtered to project '{args.project}')" if args.project else ""))
    if not eligible:
        print("Nothing to do.")
        return

    # Show breakdown by project
    by_proj: dict = {}
    for r in eligible:
        by_proj.setdefault(r.get("project_id", "?"), []).append(r)
    print("\nBreakdown by project_id:")
    for pid, ts in sorted(by_proj.items(), key=lambda x: -len(x[1])):
        print(f"  {pid}: {len(ts)} tasks")

    if not args.commit:
        print(f"\nDry-run — {len(eligible)} tasks would be re-queued as QUEUED.")
        print("Re-run with --commit to write changes.")
        return

    total = 0
    batches = [eligible[i: i + args.batch_size] for i in range(0, len(eligible), args.batch_size)]
    for b_idx, batch in enumerate(batches):
        print(f"\nBatch {b_idx + 1}/{len(batches)} ({len(batch)} tasks)…", flush=True)
        for r in batch:
            try:
                db.update("tasks", {"id": r["id"]},
                          {"state": "QUEUED", "note": "backfill: re-queued for judge+auto-merge policy"})
                total += 1
                print(f"  queued {r['slug'][:60]}", flush=True)
            except Exception as e:
                print(f"  SKIP {r['slug'][:60]}: {e}", flush=True)
        if b_idx < len(batches) - 1:
            print(f"  waiting {args.delay_seconds}s before next batch…", flush=True)
            time.sleep(args.delay_seconds)

    print(f"\nDone: {total}/{len(eligible)} tasks re-queued.")


if __name__ == "__main__":
    main()
