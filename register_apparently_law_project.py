#!/usr/bin/env python3
"""Insert an 'apparently-law' row into the projects table so the intake router can route to it.
Clones the shape of the existing 'apparently' project (to pick up whatever columns exist in this
prod schema) and overrides the identity fields. Idempotent.
Run:  python3 ~/Documents/beethoven/claude-orchestrator/register_apparently_law_project.py
"""
import os, sys, uuid
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner"))
import db

existing = db.select("projects", {"name": "eq.apparently-law", "limit": "1"}) or []
if existing:
    print("apparently-law project row already exists ->", existing[0].get("id"))
    sys.exit(0)

tmpl = (db.select("projects", {"name": "eq.apparently", "limit": "1"}) or [None])[0]
if not tmpl:
    print("ERROR: could not read the 'apparently' project as a template"); sys.exit(1)

row = dict(tmpl)
# fresh identity + apparently-law specifics; drop server-managed fields
row.pop("id", None); row.pop("created_at", None); row.pop("updated_at", None)
row["name"] = "apparently-law"
row["repo_path"] = "/Users/kpasch/Documents/apparently-law"
for k, v in list(row.items()):
    if isinstance(v, str) and ("apparently" in v.lower()) and k not in ("name", "repo_path"):
        # retarget repo/remote/vercel-ish fields to apparently-law
        row[k] = v.replace("apparently", "apparently-law") if "apparently-law" not in v else v
# common branch fields -> main
for bk in ("default_base", "prod_branch", "branch"):
    if bk in row:
        row[bk] = "main"

try:
    res = db.insert("projects", row)
    print("inserted apparently-law project:", (res or [{}]))
except Exception as e:
    print("insert failed:", e)
    print("row attempted:", {k: row[k] for k in ("name", "repo_path") if k in row})
    sys.exit(1)
