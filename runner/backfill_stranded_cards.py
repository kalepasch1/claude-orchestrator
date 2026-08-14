"""
backfill_stranded_cards.py — one-shot reconciler for the DONE-before-card bug.

WHAT WENT WRONG
    cowork_executor.py wrote state=DONE BEFORE filing the integration card and swallowed
    any failure of the card write (see the comment block at the fix site). Three silent
    paths ended at DONE-with-no-card: a crash in the window between the two writes, a
    raising card write, and ensure_integration_card returning False because nothing was
    created. A DONE task holding a pushed agent branch and no approvals row is invisible
    to the merge train permanently — the work exists on origin and nothing will ever look
    at it. Measured 2026-08-06: 36 of 111 tasks that reached DONE in 12 hours (32%) had no
    approvals row at all.

WHAT THIS DOES
    Finds DONE tasks with an artifact_branch and no live merge card, and files the missing
    card. Nothing else.

WHAT THIS DELIBERATELY DOES NOT DO
    - It never modifies task state. Not one UPDATE against `tasks`. This is a repair of
      missing derived rows, not a bulk state change, and keeping it read-only against
      `tasks` is what makes it safe to re-run.
    - It does not touch tasks whose branch no longer exists on origin. Those are a
      different failure (lost work, not unqueued work) and belong to the recovery engine;
      filing a card for a vanished branch just moves the strand into the train.

SAFETY PROPERTIES
    - idempotent: existence is re-checked per slug immediately before each insert, so a
      second run inserts nothing.
    - individual inserts, never a bulk write.
    - batched with a checkpoint file, so an interrupted run resumes instead of restarting.
    - --dry-run by default in spirit: --apply is required to write anything.

Usage:
    python3 backfill_stranded_cards.py                 # report only
    python3 backfill_stranded_cards.py --apply         # file missing cards
    python3 backfill_stranded_cards.py --apply --limit 500 --batch 25
"""
import argparse
import json
import os
import subprocess
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

import db  # noqa: E402
import merge_train  # noqa: E402

CHECKPOINT = os.path.join(
    os.environ.get("CLAUDE_ORCH_HOME",
                   os.path.join(os.path.dirname(_DIR), ".runtime")),
    "backfill-stranded-cards.checkpoint.json")

PROVENANCE = ("backfill_stranded_cards: card was never filed because cowork_executor "
              "marked the task DONE before writing the card and swallowed the failure "
              "(fixed 2026-08-06); reconciled after the fact")


def _load_checkpoint():
    try:
        with open(CHECKPOINT) as f:
            return set(json.load(f).get("done_ids") or [])
    except Exception:
        return set()


def _save_checkpoint(done_ids):
    try:
        os.makedirs(os.path.dirname(CHECKPOINT), exist_ok=True)
        with open(CHECKPOINT, "w") as f:
            json.dump({"done_ids": sorted(done_ids)}, f)
    except Exception as e:
        print(f"[checkpoint] could not persist: {e}")


def _branch_on_origin(repo_path, branch):
    """True when the branch still exists on origin.

    A missing branch means the work itself is gone, which is the recovery engine's
    problem, not this script's. Fail CLOSED: if we cannot tell, we do not file a card.
    """
    if not repo_path or not os.path.isdir(repo_path) or not branch:
        return False
    try:
        r = subprocess.run(["git", "ls-remote", "--exit-code", "--heads", "origin", branch],
                           cwd=repo_path, capture_output=True, text=True, timeout=60)
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def find_stranded(limit=500):
    """DONE tasks with a pushed branch and no live merge card."""
    projects = {p["id"]: p for p in (db.select("projects") or [])}
    rows = db.select("tasks", {
        "select": "id,slug,project_id,state,note,artifact_branch,updated_at",
        "state": "eq.DONE",
        "artifact_branch": "not.is.null",
        "order": "updated_at.desc",
        "limit": str(limit),
    }) or []
    stranded = []
    for t in rows:
        slug = t.get("slug")
        if not slug:
            continue
        # Targeted per-slug lookup — the same server-side query the fixed
        # ensure_integration_card uses. A client-side scan here would reproduce
        # exactly the window bug this whole change is about.
        if merge_train._find_existing_card(slug):
            continue
        proj = projects.get(t.get("project_id")) or {}
        stranded.append({
            "id": t["id"],
            "slug": slug,
            "branch": t.get("artifact_branch"),
            "project": proj.get("name") or str(t.get("project_id")),
            "repo_path": proj.get("repo_path"),
        })
    return stranded


def run(limit=500, batch=25, apply=False, verify_branch=True):
    stranded = find_stranded(limit=limit)
    already = _load_checkpoint()
    todo = [s for s in stranded if s["id"] not in already]
    print(f"stranded DONE tasks with no card: {len(stranded)} "
          f"({len(stranded) - len(todo)} already handled in a prior run)")

    filed = skipped_missing_branch = failed = 0
    processed = set(already)

    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        for s in chunk:
            if verify_branch and not _branch_on_origin(s["repo_path"], s["branch"]):
                skipped_missing_branch += 1
                print(f"  skip (branch not on origin -> recovery engine): "
                      f"{s['slug']} [{s['branch']}]")
                continue
            if not apply:
                print(f"  would file card: {s['project']}/{s['slug']} [{s['branch']}]")
                filed += 1
                continue
            # Re-check immediately before writing. This is the idempotency guarantee:
            # a concurrent executor may have filed the card since find_stranded() ran.
            if merge_train._find_existing_card(s["slug"]):
                processed.add(s["id"])
                continue
            state = merge_train.ensure_integration_card_result(
                s["project"], s["slug"],
                kind="integrate",
                title=f"merge of {s['slug']}",
                why=PROVENANCE,
                detail=f"branch={s['branch']} backfilled by backfill_stranded_cards.py",
                status="approved",
                decided_by="canonical-train:backfill-stranded-cards",
            )
            if state in merge_train.CARD_OK:
                filed += 1
                processed.add(s["id"])
                print(f"  filed: {s['project']}/{s['slug']} [{s['branch']}] ({state})")
            else:
                failed += 1
                print(f"  FAILED: {s['project']}/{s['slug']} [{s['branch']}]")
        if apply:
            _save_checkpoint(processed)

    out = {"stranded": len(stranded), "filed": filed,
           "skipped_missing_branch": skipped_missing_branch, "failed": failed,
           "applied": apply}
    print(f"backfill_stranded_cards: {out}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--batch", type=int, default=25)
    ap.add_argument("--apply", action="store_true",
                    help="actually file the missing cards (default: report only)")
    ap.add_argument("--no-verify-branch", action="store_true",
                    help="do not check that the branch still exists on origin (not recommended)")
    args = ap.parse_args()
    run(limit=args.limit, batch=args.batch, apply=args.apply,
        verify_branch=not args.no_verify_branch)


if __name__ == "__main__":
    main()
