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
import os, sys, json, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

TOKEN = os.environ.get("SUPABASE_ACCESS_TOKEN")
SCAN_SQL = ("select count(*) filter (where not rowsecurity) as off, count(*) as total "
            "from pg_tables where schemaname='public'")

# The Management API returns 409 Conflict when another operation holds the project
# (a migration, a branch op, a concurrent query). It is transient, but an unretried
# 409 propagated out of _query() and aborted the scan for that app — the recorded
# `HTTP Error 409: Conflict` failure on this gate. 429 and 5xx are the same class.
_RETRY_STATUS = (409, 429, 500, 502, 503, 504)
_RETRY_BACKOFF_S = (1.0, 2.0, 4.0)   # 3 retries, exponential

# Apps/tables that are intentionally anon-readable (public reference data, marketing
# tables). Listed here they are still recorded in security_posture but never file a
# remediation task, so the gate stops re-filing a ticket the operator already judged.
_ALLOWLIST_FILENAME = ".rlsallowlist.json"


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_allowlist(path=None):
    """Read `.rlsallowlist.json` -> {"apps": [...]}. Fail-soft: bad/missing file = {}.

    Accepts either {"apps": ["x"]} or a bare ["x"] list so a hand-edited file still works.
    """
    path = path or os.path.join(_repo_root(), _ALLOWLIST_FILENAME)
    try:
        with open(path) as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {"apps": []}
    except Exception as e:
        print(f"rls_guard: ignoring unreadable {_ALLOWLIST_FILENAME} ({e})")
        return {"apps": []}
    if isinstance(data, list):
        return {"apps": [str(a) for a in data]}
    if isinstance(data, dict):
        return {"apps": [str(a) for a in (data.get("apps") or [])]}
    return {"apps": []}


def _sleep(seconds):
    """Indirection so tests do not actually wait out the backoff."""
    time.sleep(seconds)


def _query(ref, sql, retries=_RETRY_BACKOFF_S):
    """POST a read-only query to the Management API, retrying transient conflicts.

    Retries on 409/429/5xx with 1s, 2s, 4s backoff. Any other HTTPError (401, 404 —
    a bad token or a deleted project) is raised immediately; retrying those just
    delays a real failure.
    """
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{ref}/database/query",
        data=json.dumps({"query": sql}).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method="POST")
    attempts = len(retries) + 1
    for attempt in range(attempts):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            if e.code not in _RETRY_STATUS or attempt == attempts - 1:
                raise
            delay = retries[attempt]
            print(f"rls_guard: {ref} HTTP {e.code}; retry {attempt + 1}/{len(retries)} in {delay}s")
            _sleep(delay)


def _open_task_exists(app):
    rows = db.select("tasks", {"select": "id", "slug": f"eq.sec-rls-{app}",
                              "state": "in.(QUEUED,RUNNING,WAITING,RETRY)"}) or []
    return len(rows) > 0


def run():
    if not TOKEN:
        print("rls_guard: SUPABASE_ACCESS_TOKEN unset; skipping"); return
    apps = db.select("security_posture", {"select": "app,project_ref"}) or []
    allowlisted = set(_load_allowlist().get("apps") or [])
    filed = 0
    skipped = 0
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
        # Posture is always recorded above; the allowlist only suppresses ticket-filing,
        # so an intentionally-anon app stays visible without re-filing a closed ticket.
        if app in allowlisted:
            skipped += 1
            continue
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
    print(f"rls_guard: rescanned {len(apps)} apps, filed {filed} remediation tasks"
          f"{f', {skipped} allowlisted' if skipped else ''}")


if __name__ == "__main__":
    run()
