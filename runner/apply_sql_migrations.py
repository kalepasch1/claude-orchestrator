#!/usr/bin/env python3
"""Apply selected idempotent SQL migrations through the Supabase Management API.

MAIN-ONLY (owner decision 2026-10-03): every file is checked by migration_main_guard before a
single statement runs. The target ref must map to a repo + production branch in
runner/deployment_bindings.json; the file must exist byte-identical on that branch (fetched
fresh through the checkout the file lives in); its version must not collide with the
production ledger; destructive SQL also needs --owner-approved <version>. The SQL that runs
is the verified bytes. Refusals are printed, written to fleet_log, and returned under
"refused"; nothing is applied from a feature branch.

    python3 runner/apply_sql_migrations.py [--ref REF] [--owner-approved VERSION ...] FILE...
"""
import argparse
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # loads runner/.env
import migration_main_guard as guard


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULTS = [
    "supabase/migrations/0028_controls_key_value_flags.sql",
    "supabase/migrations/0029_orchestrator_routing_telemetry.sql",
    "supabase/migrations/0030_reuse_and_verifier_intelligence.sql",
]


def _split(sql):
    parts, cur, quote, dollar = [], [], None, None
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i:i + 2]
        if dollar:
            if sql.startswith(dollar, i):
                cur.append(dollar)
                i += len(dollar)
                dollar = None
                continue
            cur.append(ch)
            i += 1
            continue
        if quote is None and nxt == "--":
            j = sql.find("\n", i)
            if j == -1:
                break
            i = j + 1
            continue
        if quote is None and ch == "$":
            m = re.match(r"\$[A-Za-z_0-9]*\$", sql[i:])
            if m:
                dollar = m.group(0)
                cur.append(dollar)
                i += len(dollar)
                continue
        if ch in ("'", '"'):
            if quote == ch:
                quote = None
            elif quote is None:
                quote = ch
        if ch == ";" and quote is None:
            stmt = "".join(cur).strip()
            if stmt:
                parts.append(stmt)
            cur = []
        else:
            cur.append(ch)
        i += 1
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


def _query(ref, token, sql):
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{ref}/database/query",
        data=json.dumps({"query": sql}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST")
    raw = urllib.request.urlopen(req, timeout=60).read().decode()
    return json.loads(raw) if raw else None


def _read_ledger(ref, token):
    return guard.read_ledger(ref, query=lambda sql: _query(ref, token, sql))


def apply(paths, ref=None, owner_approved=()):
    """{"applied": [...], "skipped": [...], "refused": [decision, ...]} — a file is applied
    only when migration_main_guard says it is on the target's production branch."""
    token = os.environ.get("SUPABASE_ACCESS_TOKEN")
    ref = ref or os.environ.get("SUPABASE_PROJECT_REF")
    if not token or not ref:
        raise SystemExit("SUPABASE_ACCESS_TOKEN and SUPABASE_PROJECT_REF are required")
    target = guard.resolve_target(ref=ref)
    ledger = _read_ledger(ref, token) if target else None
    applied, skipped, refused = [], [], []
    for rel in paths:
        path = rel if os.path.isabs(rel) else os.path.join(ROOT, rel)
        decision = guard.check_file(path, target, ledger=ledger, owner_approved=owner_approved)
        if not decision.get("ok"):
            if not target:
                decision["reason"] = ("refused %s: Supabase ref %s has no production repo/branch mapping "
                                      "in runner/deployment_bindings.json" % (os.path.basename(rel), ref))
            guard.record_refusal(decision, via="apply_sql_migrations")
            refused.append({k: v for k, v in decision.items() if k != "sql"})
            continue
        if decision.get("already_applied"):
            skipped.append(rel)
            continue
        for stmt in _split(decision["sql"].decode("utf-8")):
            _query(ref, token, stmt)
        applied.append(rel)
    return {"applied": applied, "skipped": skipped, "refused": refused}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--ref", default=None, help="Supabase project ref (default SUPABASE_PROJECT_REF)")
    ap.add_argument("--owner-approved", action="append", default=[], metavar="VERSION",
                    help="owner-approved version for a destructive migration (repeatable)")
    a = ap.parse_args()
    result = apply(a.paths or DEFAULTS, ref=a.ref, owner_approved=a.owner_approved)
    print(json.dumps(result, indent=2, default=str))
    sys.exit(1 if result["refused"] else 0)
