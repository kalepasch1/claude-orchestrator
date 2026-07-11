#!/usr/bin/env python3
"""
quarantine_breakdown.py — category breakdown of QUARANTINED tasks for a given project,
parsed from the "blocker-quarantine: quarantined as <category>; ..." note prefix that
blocker_quarantine.py writes. Also samples a few raw notes per category so we can see
whether the classification looks correct.

Usage: python3 quarantine_breakdown.py [project_name]   (default: beethoven)
"""
import os
import re
import sys
import collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.isfile(env_path):
    for line in open(env_path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k, v.strip().strip('"').strip("'"))

import db  # noqa: E402

PROJECT_NAME = sys.argv[1] if len(sys.argv) > 1 else "beethoven"

NOTE_RE = re.compile(r"quarantined as (?P<category>[a-z-]+);", re.I)


def main():
    projects = db.select("projects", {"select": "id,name"}) or []
    pid = None
    for p in projects:
        if p.get("name") == PROJECT_NAME:
            pid = p.get("id")
            break
    if not pid:
        print(f"project '{PROJECT_NAME}' not found")
        return

    total = db.count("tasks", {"state": "eq.QUARANTINED", "project_id": f"eq.{pid}"})
    print(f"Project: {PROJECT_NAME} ({pid})")
    print(f"Total QUARANTINED: {total}\n")

    # Pull a large sample (paged) of notes to categorize. count=exact told us the total;
    # now page through in chunks of 1000 (PostgREST cap) to get every note, not just first 1000.
    offset = 0
    page = 1000
    cat_counts = collections.Counter()
    cat_samples = collections.defaultdict(list)
    uncategorized_samples = []
    fetched = 0
    while True:
        rows = db.select(
            "tasks",
            {
                "select": "id,slug,note",
                "state": "eq.QUARANTINED",
                "project_id": f"eq.{pid}",
                "order": "id.asc",
                "limit": str(page),
                "offset": str(offset),
            },
        ) or []
        if not rows:
            break
        fetched += len(rows)
        for r in rows:
            note = str(r.get("note") or "")
            m = NOTE_RE.search(note)
            if m:
                cat = m.group("category").lower()
                cat_counts[cat] += 1
                if len(cat_samples[cat]) < 3:
                    cat_samples[cat].append((r.get("slug"), note[:250]))
            else:
                cat_counts["(unparsed)"] += 1
                if len(uncategorized_samples) < 3:
                    uncategorized_samples.append((r.get("slug"), note[:250]))
        if len(rows) < page:
            break
        offset += page

    print(f"Fetched {fetched} QUARANTINED rows for category breakdown.\n")
    print("=" * 70)
    print("CATEGORY BREAKDOWN")
    print("=" * 70)
    for cat, n in cat_counts.most_common():
        pct = 100 * n / fetched if fetched else 0
        print(f"  {cat:16s} {n:5d}  ({pct:.1f}%)")

    print()
    print("=" * 70)
    print("SAMPLE NOTES PER CATEGORY (up to 3 each)")
    print("=" * 70)
    for cat, samples in cat_samples.items():
        print(f"\n--- {cat} ---")
        for slug, note in samples:
            print(f"  [{slug}] {note}")
    if uncategorized_samples:
        print("\n--- (unparsed) ---")
        for slug, note in uncategorized_samples:
            print(f"  [{slug}] {note}")


if __name__ == "__main__":
    main()
