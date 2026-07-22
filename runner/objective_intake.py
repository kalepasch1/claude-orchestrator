#!/usr/bin/env python3
"""
objective_intake.py - Ingest a flat list of objectives from intake/objectives.md into the
goals table. Idempotent: objectives whose title already exists are skipped. Malformed lines
are logged and skipped without crashing.

Format of intake/objectives.md:
    # Objectives
    - Raise test coverage to 80% | metric: coverage_pct | target: 80 | project: beethoven
    - Reduce p95 latency by 30% | metric: p95_ms | target: 200 | project: smarter
    - Zero gitleaks findings | metric: gitleaks_count | target: 0

Each line starts with '- ' and has pipe-separated fields. Only the first field (objective
title) is required; metric, target, project, and priority are optional.

Run: python3 objective_intake.py
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

HERE = os.path.dirname(os.path.abspath(__file__))
OBJECTIVES_PATH = os.path.abspath(os.path.join(HERE, "..", "intake", "objectives.md"))


def parse_objectives(text):
    """Parse flat list of objectives. Returns list of dicts, skips malformed lines."""
    results = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or not line.startswith("-"):
            continue
        line = line.lstrip("- ").strip()
        if not line:
            continue
        try:
            parts = [p.strip() for p in line.split("|")]
            objective = parts[0]
            if not objective:
                continue
            row = {"objective": objective, "status": "active"}
            for part in parts[1:]:
                part = part.strip()
                if not part:
                    continue
                m = re.match(r"^(\w+)\s*:\s*(.+)$", part)
                if m:
                    key, val = m.group(1).lower(), m.group(2).strip()
                    if key in ("metric", "target", "project", "priority"):
                        row[key] = val
            results.append(row)
        except Exception as e:
            sys.stderr.write(f"[objective_intake] line {lineno}: parse error: {e}\n")
    return results


def ingest(path=None):
    """Read objectives from file, insert new ones idempotently. Returns (inserted, skipped)."""
    path = path or OBJECTIVES_PATH
    if not os.path.isfile(path):
        print(f"objective_intake: no file at {path}")
        return 0, 0
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except Exception as e:
        sys.stderr.write(f"[objective_intake] read error: {e}\n")
        return 0, 0

    objectives = parse_objectives(text)
    if not objectives:
        print("objective_intake: no objectives found in file")
        return 0, 0

    # Get existing objectives for idempotency
    existing = set()
    try:
        rows = db.select("goals", {"select": "objective"}) or []
        existing = {r.get("objective", "").strip().lower() for r in rows}
    except Exception:
        pass

    inserted, skipped = 0, 0
    for obj in objectives:
        key = obj["objective"].strip().lower()
        if key in existing:
            skipped += 1
            continue
        try:
            db.insert("goals", obj)
            existing.add(key)
            inserted += 1
        except Exception as e:
            sys.stderr.write(f"[objective_intake] insert error for '{obj['objective'][:40]}': {e}\n")
            skipped += 1

    print(f"objective_intake: inserted {inserted}, skipped {skipped} (already exist or error)")
    return inserted, skipped


def run():
    return ingest()


if __name__ == "__main__":
    run()
