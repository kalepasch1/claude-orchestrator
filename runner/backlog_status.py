#!/usr/bin/env python3
"""
backlog_status.py — accurate (exact-count) snapshot of the fleet's real backlog, per project.
Run from ~/claude-orchestrator/runner (needs the same DB env as the runner itself).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.isfile(env_path):
    for line in open(env_path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k, v.strip().strip('"').strip("'"))

import db  # noqa: E402

STATES = ["QUEUED", "RUNNING", "DONE", "BLOCKED", "CONFLICT", "TESTFAIL", "RETRY", "QUARANTINED", "MERGED"]


def main():
    """Print exact task-state counts fleet-wide and per project to stdout."""
    projects = db.select("projects", {"select": "id,name"}) or []
    pid_to_name = {p["id"]: p["name"] for p in projects}

    print("=" * 78)
    print("EXACT TASK STATE COUNTS (fleet-wide, then per project)")
    print("=" * 78)
    grand_total = 0
    for state in STATES:
        try:
            n = db.count("tasks", {"state": f"eq.{state}"})
        except Exception as e:
            print(f"{state}: count failed ({e})")
            continue
        grand_total += n if state != "MERGED" else 0
        print(f"\n{state}: {n} total")
        if n and n <= 20000:
            for pid, pname in pid_to_name.items():
                try:
                    pn = db.count("tasks", {"state": f"eq.{state}", "project_id": f"eq.{pid}"})
                except Exception:
                    pn = "?"
                if pn:
                    print(f"    {pname:24s} {pn}")

    print()
    print("=" * 78)
    print(f"BACKLOG (not yet MERGED, excluding QUARANTINED): ~{grand_total} tasks")
    print("=" * 78)

    print()
    print("=" * 78)
    print("EXACT APPROVED MERGE-KIND CARD COUNT (ready-to-ship backlog)")
    print("=" * 78)
    try:
        n = db.count("approvals", {"status": "eq.approved", "kind": "in.(verify,material,integrate)"})
        print(f"Total approved merge-kind cards: {n}")
    except Exception as e:
        print(f"count failed: {e}")


if __name__ == "__main__":
    main()
