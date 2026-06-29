#!/usr/bin/env python3
"""
operator_backfill.py — make every OPERATOR item individually reviewable in the app.

Older intake processing bundled all of a file's OPERATOR items into ONE approval card,
so they could only be approved as a lump. This one-shot scans intake/processed/*.md
(plus any not-yet-processed intake/*.md), re-parses the OPERATOR blocks, and creates one
approval card PER item via the shared intake_watcher.emit_operator_cards (idempotent by
title — safe to re-run). The live watcher now does this for all future drops.

Optionally (--clear-bundled) it denies the legacy "Operator actions from <file>" lump
cards so the dashboard shows only the per-item ones.

Run on the runner Mac (needs SUPABASE_URL + SUPABASE_SERVICE_KEY):
    python3 runner/operator_backfill.py                       # dry-run (lists items)
    python3 runner/operator_backfill.py --commit              # create per-item cards
    python3 runner/operator_backfill.py --commit --clear-bundled
"""
import os, sys, glob, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, intake_watcher

HERE = os.path.dirname(os.path.abspath(__file__))
INTAKE = os.path.abspath(os.path.join(HERE, "..", "intake"))
PROCESSED = os.path.join(INTAKE, "processed")


def iter_files():
    files = sorted(glob.glob(os.path.join(PROCESSED, "*.md")))
    files += sorted(glob.glob(os.path.join(INTAKE, "*.md")))
    return [f for f in files if os.path.isfile(f)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="create the per-item cards (default: dry-run)")
    ap.add_argument("--clear-bundled", action="store_true", help="deny legacy lump cards after backfill")
    args = ap.parse_args()

    seen, created = 0, 0
    for f in iter_files():
        text = open(f, encoding="utf-8", errors="replace").read()
        tasks, operator = intake_watcher.parse(text)
        if not operator:
            continue
        proj = tasks[0]["project"] if tasks else "intake"
        base = os.path.basename(f)
        print(f"\n{base}  (project={proj}) — {len(operator)} operator item(s):")
        for o in operator:
            print(f"   • {o[:100]}")
        seen += len(operator)
        if args.commit:
            created += intake_watcher.emit_operator_cards(proj, operator, base)

    print(f"\n{'Created' if args.commit else 'Would create'} per-item operator cards. "
          f"items_seen={seen}" + (f", new_cards={created}" if args.commit else ""))

    if args.commit and args.clear_bundled:
        lumps = db.select("approvals", {"select": "id", "title": "like.Operator actions from*",
                                        "status": "eq.pending"}) or []
        for a in lumps:
            db.update("approvals", {"id": a["id"]}, {"status": "denied", "decided_by": "superseded-by-backfill"})
        print(f"cleared {len(lumps)} legacy bundled card(s)")

    if not args.commit:
        print("\nDry-run only — no DB writes. Re-run with --commit on the runner Mac "
              "(SUPABASE_SERVICE_KEY set). Add --clear-bundled to retire the old lump cards.")


if __name__ == "__main__":
    main()
