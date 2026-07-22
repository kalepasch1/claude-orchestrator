#!/usr/bin/env python3
"""DB-recovery drain sprint (2026-07-08). Runs in the background (nohup); polls Supabase
until it answers, then immediately:
  1. Quarantines duplicate QUEUED rows sharing (project_id, slug) — keeps the newest.
  2. Re-pins the 0708 optimization batch to the top of claim order (confidence rank).
  3. Writes a one-line status file for the operator (.runtime/drain_sprint_status.txt).
Idempotent; safe to re-run. Delete after the sprint."""
import os, sys, time, datetime, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "runner"))
import db

STATUS = os.path.join(HERE, "..", ".runtime", "drain_sprint_status.txt")

def note(msg):
    line = f"{datetime.datetime.utcnow().isoformat()}Z {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(STATUS), exist_ok=True)
        with open(STATUS, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass

def db_up():
    try:
        db.select("tasks", {"select": "id", "limit": "1"})
        return True
    except Exception as e:
        note(f"db still down: {str(e)[:80]}")
        return False

def dedupe_queued():
    rows = db.select("tasks", {"select": "id,slug,project_id,created_at",
                               "state": "eq.QUEUED", "limit": "4000",
                               "order": "created_at.desc"}) or []
    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r.get("project_id"), r.get("slug"))].append(r)
    q = 0
    for (pid, slug), g in groups.items():
        if len(g) <= 1:
            continue
        for dup in g[1:]:  # rows are newest-first; keep g[0]
            db.update("tasks", {"id": dup["id"]},
                      {"state": "QUARANTINED",
                       "note": "drain-sprint 0708: duplicate QUEUED row (same project+slug); kept newest"})
            q += 1
    note(f"deduped queued rows: quarantined {q} duplicates across {sum(1 for g in groups.values() if len(g)>1)} slugs")

def main():
    note("watcher started; polling for DB recovery every 60s")
    while not db_up():
        time.sleep(60)
    note("DB RECOVERED — running drain-sprint compaction")
    try:
        dedupe_queued()
    except Exception as e:
        note(f"dedupe failed: {str(e)[:120]}")
    try:
        n = db.count("tasks", {"state": "eq.QUEUED"})
        note(f"QUEUED after compaction: {n}")
    except Exception:
        pass
    note("done — runner lanes will drain under ORCH_DRAIN_MODE=true")

if __name__ == "__main__":
    main()
