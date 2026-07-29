#!/usr/bin/env python3
"""Park the 5 monolith master-tasks so they don't integrate half-baked branches.
Run from anywhere:  python3 ~/Documents/beethoven/claude-orchestrator/remediate_monoliths.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner"))
import db

SLUGS = [
    "dropbox-apparently-merge-vigil-into-apparently-gaming-exams-for-all--master-task",
    "dropbox-illuminati-trojun-v2-the-vendor-agnostic-compliance-kernel-t-master-task",
    "dropbox-pareto-2080-luxury-consigliere-repositioning-5m-ecp-passport-master-task",
    "dropbox-smarter-embeddable-core-apparently-pareto-real-member-identi-master-task",
    "dropbox-tomorrow-publish-to-mesh-self-service-ecp-individual-path-pe-master-task",
]

for slug in SLUGS:
    try:
        r = db.update("tasks", {"slug": slug},
                      {"state": "QUARANTINED",
                       "note": "monolith superseded by sharded re-drop 2026-07-28"})
        print("parked:", slug[:60], "->", "ok" if r else "(no-op/already)")
    except Exception as e:
        print("ERROR parking", slug[:60], "->", e)
print("done")
