#!/usr/bin/env python3
"""Periodic audit/materializer for the authoritative control plane.

It does not generate tasks. In liquidation mode it safely quarantines exact
semantic duplicates, fixes impossible future timestamps, and publishes one
compact control snapshot for the UI and other schedulers.
"""
from __future__ import annotations

import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control_plane
import db
import value_ledger


def run(apply=True, limit=None):
    limit = int(limit or os.environ.get("ORCH_CONTROL_PLANE_SCAN_LIMIT", "2000"))
    rows = db.select("tasks", {
        "select": "id,slug,prompt,kind,note,state,project_id,created_at,force_coder,model,material",
        "state": "eq.QUEUED", "order": "created_at.asc", "limit": str(limit),
    }) or []
    report = control_plane.audit(rows)
    report["liquidation_active"] = control_plane.liquidation_active(queue_depth=len(rows))
    report["quarantined_duplicates"] = 0
    report["clock_repairs"] = 0
    seen = {}
    now = datetime.datetime.now(datetime.timezone.utc)

    for row in rows:
        fp = control_plane.objective_fingerprint(row)
        # Keep the oldest objective row. Independent evidence/model samples have
        # distinct fingerprints; delivery work is only collapsed on exact intent.
        if fp in seen and report["liquidation_active"] and apply:
            db.update("tasks", {"id": row["id"]}, {
                "state": "QUARANTINED",
                "note": f"control-plane: exact objective duplicate of {seen[fp].get('slug')}",
                "updated_at": "now()",
            })
            report["quarantined_duplicates"] += 1
            continue
        seen[fp] = row
        ts = control_plane._parse_time(row.get("created_at"))
        if ts and ts > now + datetime.timedelta(minutes=5) and apply:
            # created_at is server-owned; repairing to now restores FIFO/bankruptcy semantics.
            db.update("tasks", {"id": row["id"]}, {
                "created_at": "now()", "updated_at": "now()",
                "note": control_plane._append_note(row.get("note"), "control-plane: future timestamp repaired"),
            })
            report["clock_repairs"] += 1

    report["value_ledger"] = value_ledger.summary()
    report["generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        db.insert("controls", {"key": "control_plane", "value": json.dumps(report),
                               "updated_at": "now()"}, upsert=True)
    except Exception:
        pass
    print("control-plane:", json.dumps(report, sort_keys=True))
    return report


if __name__ == "__main__":
    run(apply=os.environ.get("ORCH_CONTROL_PLANE_APPLY", "true").lower() in control_plane.TRUE)
