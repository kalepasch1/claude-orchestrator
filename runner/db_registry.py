#!/usr/bin/env python3
"""
db_registry.py — the registry of databases Database Steering reviews, and how they get in.

THE GAP THIS CLOSES (2026-09-12). The fleet knew about its app databases through
`security_posture`, a table someone typed eight Supabase refs into on 2026-07-02 and never
updated. apparently-law (the firm's live production database) and illuminati were not on
it, so the only database control the fleet had never looked at them. Meanwhile the
Management API token in runner/.env can enumerate every project the account owns.

TWO WAYS IN, ONE ROW SHAPE (`db_sources`):
  1. AUTO-DISCOVERY — `discover()` lists Supabase projects through the Management API and
     upserts every ACTIVE one, matched to a fleet project by name when the names agree
     (`apparently-law` <-> projects.name `apparently-law`). Inactive/paused projects are
     recorded as `status='inactive'`, enabled=false, so the registry is a complete
     inventory but the loop wastes nothing on them. Needs no per-app credentials.
  2. OPERATOR LINKING — `add()` (used by db_link.py and the web route) registers any other
     database: AWS RDS/Aurora/Redshift, Google Cloud SQL/AlloyDB/BigQuery, Azure, Neon,
     PlanetScale, CockroachDB, Snowflake, a bare Postgres/MySQL DSN. The row carries a
     credential REFERENCE (env:/keychain:/doppler:/onepassword:/vault:/file:) — never the
     secret — resolved at query time by db_adapters. A raw DSN or password is refused at
     the door; there is no path by which a secret value reaches the control plane.

CONSISTENCY WITH rls_guard: `sync_security_posture()` backfills `security_posture` with any
discovered Supabase project it is missing, so the existing daily RLS gate covers the
whole account instead of the eight refs from July. It records posture rows only; it
never files tasks itself (rls_guard does that on its own cadence, with its allowlist).

Fail-soft throughout: discovery without a token logs and returns; a Management API hiccup
leaves the registry as it was. Nothing here talks to an app database.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402
import db_steering_contract as C  # noqa: E402

MGMT_BASE = "https://api.supabase.com/v1"
DISCOVERY_MIN_INTERVAL_S = int(os.environ.get("ORCH_DB_DISCOVERY_INTERVAL_S", "3600"))
# Supabase projects the fleet never treats as app databases (the control plane itself is
# reviewed too, but marked so remediation is not filed against it as if it were an app).
SELF_REFS = {r.strip() for r in os.environ.get("ORCH_DB_SELF_REFS", "").split(",") if r.strip()}
_RETRY_STATUS = (409, 429, 500, 502, 503, 504)
_RETRY_BACKOFF_S = (1.0, 2.0, 4.0)
_last_discovery = {"at": 0.0}


def _token():
    return os.environ.get("SUPABASE_ACCESS_TOKEN") or ""


def _sleep(seconds):
    """Indirection so tests do not wait out the backoff."""
    time.sleep(seconds)


def _mgmt_get(path, timeout=30):
    tok = _token()
    if not tok:
        raise RuntimeError("SUPABASE_ACCESS_TOKEN unset")
    req = urllib.request.Request(MGMT_BASE + path, headers={"Authorization": "Bearer " + tok})
    attempts = len(_RETRY_BACKOFF_S) + 1
    for attempt in range(attempts):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except urllib.error.HTTPError as e:
            if e.code not in _RETRY_STATUS or attempt == attempts - 1:
                raise
            _sleep(_RETRY_BACKOFF_S[attempt])


def _now():
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ── reads ─────────────────────────────────────────────────────────────────────────────

def list_sources(enabled_only=False, project=None):
    """All registered sources (never raises)."""
    params = {"select": "*", "order": "project.asc,label.asc", "limit": "500"}
    if enabled_only:
        params["enabled"] = "eq.true"
        params["status"] = "in.(active,unreachable)"
    if project:
        params["project"] = "eq.%s" % project
    try:
        return db.select("db_sources", params) or []
    except Exception as e:
        print("db_registry: list_sources failed: %s: %s" % (type(e).__name__, str(e)[:120]))
        return []


def get_source(source_id=None, provider=None, ref=None):
    try:
        if source_id:
            rows = db.select("db_sources", {"select": "*", "id": "eq.%s" % source_id, "limit": "1"}) or []
        else:
            rows = db.select("db_sources", {"select": "*", "provider": "eq.%s" % provider,
                                            "ref": "eq.%s" % ref, "limit": "1"}) or []
        return rows[0] if rows else None
    except Exception as e:
        print("db_registry: get_source failed: %s" % str(e)[:120])
        return None


def _fleet_projects():
    """{name: row} for the fleet's projects table. Fail-soft."""
    try:
        rows = db.select("projects", {"select": "id,name,repo_path,superseded_by",
                                      "order": "name.asc", "limit": "300"}) or []
    except Exception:
        rows = []
    return {r.get("name"): r for r in rows if r.get("name")}


def project_for_ref_name(name, fleet=None):
    """Match a Supabase project name to a fleet project name. Exact first, then the
    obvious aliases (a Supabase project called `apparently` belongs to the fleet's
    `apparently` project even when that repo row is archived — the DATABASE is live)."""
    fleet = fleet if fleet is not None else _fleet_projects()
    n = str(name or "").strip()
    if not n:
        return None
    if n in fleet:
        return n
    low = n.lower().replace(" ", "-")
    for cand in fleet:
        if cand.lower() == low:
            return cand
    for cand in fleet:  # archived rows carry the live name plus a suffix
        if cand.lower().startswith(low + "-archived") or cand.lower() == low + "-archived":
            return low
    return low if low else None


# ── writes ────────────────────────────────────────────────────────────────────────────

def _upsert_source(row):
    """Upsert on (provider, ref); returns the persisted row or None. Never raises."""
    row = dict(row)
    row["updated_at"] = _now()
    try:
        existing = get_source(provider=row["provider"], ref=row["ref"])
        if existing:
            patch = {k: v for k, v in row.items() if k not in ("id", "created_at")}
            # Operator choices survive re-discovery: never re-enable a paused source and
            # never overwrite a credential reference or label an operator set by hand.
            if existing.get("discovered_via") == "operator" or existing.get("status") == "paused":
                for k in ("enabled", "status", "label", "credential_ref", "project", "config"):
                    patch.pop(k, None)
            db.update("db_sources", {"id": existing["id"]}, patch)
            existing.update(patch)
            return existing
        res = db.insert("db_sources", row)
        if isinstance(res, list) and res:
            return res[0]
        if isinstance(res, dict):
            return res
        return get_source(provider=row["provider"], ref=row["ref"])
    except Exception as e:
        print("db_registry: upsert %s:%s failed: %s: %s" % (row.get("provider"), row.get("ref"),
                                                             type(e).__name__, str(e)[:160]))
        return None


def add(provider, ref, label=None, project=None, credential_ref=None, region=None,
        config=None, dialect=None, discovered_via="operator", enabled=True):
    """Register or update a database. Returns (row|None, error|None).

    The credential must be a REFERENCE; anything that looks like a value is refused here,
    before it can be written anywhere.
    """
    if provider not in C.PROVIDERS:
        return None, "unknown provider %r (known: %s)" % (provider, ", ".join(C.PROVIDERS))
    ref = str(ref or "").strip()
    if not ref:
        return None, "ref is required (project ref, host, instance or dataset)"
    if not C.credential_ref_is_reference(credential_ref or ""):
        return None, ("credential_ref must be a reference (env:NAME, keychain:NAME, doppler:PATH, "
                      "onepassword:op://..., vault:<connector-account-id>, file:/path) — never a DSN, "
                      "password or token value")
    dialect = dialect or (config or {}).get("engine") or C.PROVIDER_DEFAULT_DIALECT.get(provider, "other")
    if dialect not in C.DIALECTS:
        return None, "unknown dialect %r" % (dialect,)
    row = {
        "provider": provider, "ref": ref, "dialect": dialect,
        "label": (label or "%s %s" % (provider, ref))[:120],
        "project": project, "region": region,
        "credential_ref": credential_ref or None,
        "config": _strip_secrets(config or {}),
        "discovered_via": discovered_via,
        "status": "active" if enabled else "paused",
        "enabled": bool(enabled),
    }
    saved = _upsert_source(row)
    return (saved, None) if saved else (None, "could not persist the source (see log)")


_SECRET_KEYS = ("password", "dsn", "secret", "token", "access_token", "service_account_json",
                "private_key", "api_key", "key")


def _strip_secrets(config):
    """Config holds connection SHAPE (host, port, database, engine, arns). Any key that
    smells like a value is dropped, so a caller cannot smuggle one in through config."""
    out = {}
    for k, v in (config or {}).items():
        kl = str(k).lower()
        if any(s == kl or kl.endswith("_" + s) or kl.startswith(s + "_") for s in _SECRET_KEYS):
            continue
        if isinstance(v, str) and "://" in v and "@" in v:
            continue
        out[k] = v
    return out


def set_enabled(source_id, enabled, status=None):
    try:
        db.update("db_sources", {"id": source_id},
                  {"enabled": bool(enabled), "status": status or ("active" if enabled else "paused"),
                   "updated_at": _now()})
        return True
    except Exception as e:
        print("db_registry: set_enabled failed: %s" % str(e)[:120])
        return False


def remove(source_id):
    try:
        db.delete("db_sources", {"id": source_id})
        return True
    except Exception as e:
        print("db_registry: remove failed: %s" % str(e)[:120])
        return False


def record_scan(source_id, ok, error=None, capabilities=None):
    """Bookkeeping after a scan. Three consecutive failures mark the source unreachable
    (still enabled — it is retried, just reported honestly); one success clears it."""
    patch = {"last_scan_at": _now(), "updated_at": _now()}
    try:
        cur = get_source(source_id) or {}
        if ok:
            patch.update({"last_ok_at": _now(), "last_error": None, "consecutive_failures": 0})
            if cur.get("status") == "unreachable":
                patch["status"] = "active"
        else:
            n = int(cur.get("consecutive_failures") or 0) + 1
            patch.update({"last_error": str(error or "")[:500], "consecutive_failures": n})
            if n >= 3 and cur.get("status") == "active":
                patch["status"] = "unreachable"
        if capabilities:
            patch["capabilities"] = capabilities
        db.update("db_sources", {"id": source_id}, patch)
    except Exception as e:
        print("db_registry: record_scan failed: %s" % str(e)[:120])


# ── discovery ─────────────────────────────────────────────────────────────────────────

def discover(force=False):
    """Enumerate Supabase projects through the Management API and register them.

    Returns {"discovered": n, "active": n, "inactive": n, "skipped": reason|None}.
    Throttled to once an hour unless forced; the list changes rarely and every call is a
    network round trip on the loop's budget.
    """
    if not _token():
        return {"discovered": 0, "active": 0, "inactive": 0, "skipped": "SUPABASE_ACCESS_TOKEN unset"}
    if not force and time.time() - _last_discovery["at"] < DISCOVERY_MIN_INTERVAL_S:
        return {"discovered": 0, "active": 0, "inactive": 0, "skipped": "throttled"}
    try:
        projects = _mgmt_get("/projects") or []
    except Exception as e:
        print("db_registry: discovery failed: %s: %s" % (type(e).__name__, str(e)[:160]))
        return {"discovered": 0, "active": 0, "inactive": 0, "skipped": "management api error"}
    _last_discovery["at"] = time.time()
    fleet = _fleet_projects()
    out = {"discovered": 0, "active": 0, "inactive": 0, "skipped": None}
    for p in projects if isinstance(projects, list) else []:
        ref = p.get("id")
        if not ref:
            continue
        active = str(p.get("status") or "").upper().startswith("ACTIVE")
        name = p.get("name") or ref
        row = {
            "provider": "supabase", "ref": ref, "dialect": "postgres",
            "label": str(name)[:120],
            "project": project_for_ref_name(name, fleet),
            "region": p.get("region"),
            "credential_ref": None,  # the fleet token reaches it; nothing per-app to store
            "config": {"organization_id": p.get("organization_id"),
                       "supabase_status": p.get("status"),
                       "self": ref in SELF_REFS or name == "claude-orchestrator"},
            "discovered_via": "supabase_management_api",
            "status": "active" if active else "inactive",
            "enabled": bool(active),
        }
        if _upsert_source(row):
            out["discovered"] += 1
            out["active" if active else "inactive"] += 1
    print("db_registry: discovery registered %(discovered)d supabase projects "
          "(%(active)d active, %(inactive)d inactive)" % out)
    return out


def sync_security_posture():
    """Backfill rls_guard's registry (`security_posture`) with every active Supabase source
    it is missing, so the existing daily RLS gate covers the whole account. Returns the
    number of rows added. Never removes or rewrites an existing row."""
    try:
        have = {r.get("project_ref") for r in (db.select("security_posture", {"select": "app,project_ref"}) or [])}
    except Exception as e:
        print("db_registry: security_posture read failed: %s" % str(e)[:120])
        return 0
    added = 0
    for s in list_sources(enabled_only=True):
        if s.get("provider") != "supabase" or s.get("ref") in have:
            continue
        app = s.get("project") or s.get("label") or s.get("ref")
        try:
            db.insert("security_posture", {"app": app, "project_ref": s["ref"],
                                           "total_tables": 0, "rls_off": 0, "status": "unknown"})
            have.add(s["ref"])
            added += 1
        except Exception as e:
            print("db_registry: posture backfill %s failed: %s" % (app, str(e)[:120]))
    if added:
        print("db_registry: security_posture backfilled with %d supabase projects" % added)
    return added


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Database Steering registry")
    ap.add_argument("cmd", choices=["list", "discover", "sync-posture"])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.cmd == "discover":
        print(json.dumps(discover(force=a.force), indent=2))
    elif a.cmd == "sync-posture":
        print(json.dumps({"added": sync_security_posture()}))
    else:
        for s in list_sources():
            print("%-10s %-24s %-28s %-9s %-8s cred=%s" % (
                s.get("provider"), (s.get("ref") or "")[:24], (s.get("project") or s.get("label") or "")[:28],
                s.get("status"), "on" if s.get("enabled") else "off",
                (s.get("credential_ref") or "fleet-token").split(":")[0]))
