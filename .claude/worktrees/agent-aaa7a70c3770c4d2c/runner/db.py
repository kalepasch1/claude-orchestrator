#!/usr/bin/env python3
"""
db.py - tiny Supabase (PostgREST) client over urllib. No third-party deps.
The runner uses the SERVICE ROLE key so it bypasses RLS. Set:
    SUPABASE_URL=https://<ref>.supabase.co
    SUPABASE_SERVICE_KEY=<service-role key>   (keep secret; never ship to the web app)
"""
import os, json, urllib.request, urllib.parse

# Load runner/.env directly from Python so launchd agents pick up all env vars
# (EMBED_PROVIDER, ANTHROPIC_API_KEY, etc.) even when the shell wrapper can't
# source the file due to macOS TCC restrictions.
def _load_env():
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        for raw in open(env):
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.split("#")[0].strip().strip('"').strip("'")
            os.environ.setdefault(k, v)
    except OSError:
        pass  # silently skip if FDA not yet granted; plist env vars are the fallback

_load_env()

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


def _req(method, path, body=None, headers=None, params=None):
    if not URL or not KEY:
        raise RuntimeError("set SUPABASE_URL and SUPABASE_SERVICE_KEY")
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}",
         "Content-Type": "application/json"}
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path + qs, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else None


def select(table, params=None):
    return _req("GET", f"/rest/v1/{table}", params=params or {"select": "*"})


def insert(table, row, upsert=False):
    h = {"Prefer": "return=representation" + (",resolution=merge-duplicates" if upsert else "")}
    return _req("POST", f"/rest/v1/{table}", body=row, headers=h)


def update(table, match, patch):
    params = {k: f"eq.{v}" for k, v in match.items()}
    return _req("PATCH", f"/rest/v1/{table}", body=patch,
                headers={"Prefer": "return=representation"}, params=params)


def rpc(fn, args):
    return _req("POST", f"/rest/v1/rpc/{fn}", body=args)


def claim_task(runner_id):
    """Atomically grab one QUEUED task whose deps are satisfied. Returns task or None."""
    queued = select("tasks", {"select": "*", "state": "eq.QUEUED", "order": "created_at.asc"})
    done = {t["slug"] for t in select("tasks", {"select": "slug", "state": "in.(DONE,MERGED)"})}
    for t in queued or []:
        if all(d in done for d in (t.get("deps") or [])):
            # optimistic claim: flip to RUNNING only if still QUEUED
            res = _req("PATCH", "/rest/v1/tasks",
                       body={"state": "RUNNING", "account": runner_id, "updated_at": "now()"},
                       headers={"Prefer": "return=representation"},
                       params={"id": f"eq.{t['id']}", "state": "eq.QUEUED"})
            if res:
                return res[0]
    return None


def heartbeat(runner_id, hostname, active):
    insert("runner_heartbeats",
           {"runner_id": runner_id, "hostname": hostname, "active_tasks": active,
            "last_seen": "now()"}, upsert=True)
