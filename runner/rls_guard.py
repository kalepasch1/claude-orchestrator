#!/usr/bin/env python3
"""
rls_guard.py — standing security control for Row-Level-Security across every app DB.

Registered as the 'security_rls' loop. Each run it re-scans every app's public schema for tables with
RLS DISABLED (exposed to the anon key), records the posture in security_posture, and — if an app is
exposed and has no open remediation task — files a sec-rls-<app> bugfix task so the runner adds proper
owner-scoped policies. It NEVER blanket-enables RLS itself (that would break anon-dependent apps); it
detects + routes, and the per-app agent writes correct policies with tests.

Uses the Supabase Management API (SUPABASE_ACCESS_TOKEN) so it can read any project's schema without
per-app DB creds. Fail-soft: no token -> logs and skips.
"""
import os, sys, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

TOKEN = os.environ.get("SUPABASE_ACCESS_TOKEN")
SCAN_SQL = ("select count(*) filter (where not rowsecurity) as off, count(*) as total "
            "from pg_tables where schemaname='public'")


def _query(ref, sql):
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{ref}/database/query",
        data=json.dumps({"query": sql}).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def _open_task_exists(app):
    rows = db.select("tasks", {"select": "id", "slug": f"eq.sec-rls-{app}",
                              "state": "in.(QUEUED,RUNNING,WAITING,RETRY)"}) or []
    return len(rows) > 0


def run():
    if not TOKEN:
        print("rls_guard: SUPABASE_ACCESS_TOKEN unset; skipping"); return
    apps = db.select("security_posture", {"select": "app,project_ref"}) or []
    filed = 0
    for a in apps:
        app, ref = a["app"], a.get("project_ref")
        if not ref:
            continue
        try:
            res = _query(ref, SCAN_SQL)
            row = res[0] if isinstance(res, list) else (res.get("result") or [{}])[0]
            off, total = int(row.get("off", 0)), int(row.get("total", 0))
        except Exception as e:
            print(f"rls_guard {app}: scan error {e}"); continue
        db.rpc("record_posture", {"p_app": app, "p_ref": ref, "p_total": total, "p_off": off})
        # route remediation for material exposure (skip the orchestrator's own DB + tiny counts)
        if off > 5 and app not in ("claude-orchestrator", "beethoven") and not _open_task_exists(app):
            proj = (db.select("projects", {"select": "id", "name": f"eq.{app}"}) or [{}])[0].get("id")
            if proj:
                db.insert("tasks", {"project_id": proj, "slug": f"sec-rls-{app}", "kind": "bugfix",
                    "state": "QUEUED", "note": "auto-filed by rls_guard",
                    "prompt": (f"SECURITY: {off}/{total} public tables have RLS disabled and this app uses the "
                               "anon key client-side. Add owner-scoped RLS policies (auth.uid()/household-scoped, "
                               "mirroring apparently which has RLS on all tables) and enable RLS on every public "
                               "table. Do NOT enable RLS without policies (breaks the client). Verify per-user "
                               "isolation + app still works with tests. Ship in safe batches.")})
                filed += 1
    print(f"rls_guard: rescanned {len(apps)} apps, filed {filed} remediation tasks")


if __name__ == "__main__":
    run()
