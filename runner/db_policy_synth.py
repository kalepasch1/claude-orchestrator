#!/usr/bin/env python3
"""db_policy_synth.py — candidate RLS policies where probes can't decide but code can hint.

The rls_enabled_no_policy / rls_disabled_tables findings are deliberately NOT in
db_remediate's mechanical set: a wrong policy is worse than an open gap. But "no policy to
write" isn't true either — most tables hint their tenancy (user_id / owner_id / account_id /
tenant_id / *_email columns, or FK to a users/accounts table via the FK graph). This module
generates a CONSERVATIVE candidate migration per table: deny-by-default posture plus a
commented policy skeleton keyed to the detected owner column. It can go out as a draft PR
labeled policy-design via db_remediate's PR machinery; nothing here is meant to merge
unreviewed — the value is a starting point with citations instead of a blank page.

Deterministic by construction (no model); facts come from the latest snapshot's
fk_edges/columns inventories. Default OFF: ORCH_DB_POLICY_SYNTH=1 enables.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402
import db_chains  # noqa: E402 — SNAPSHOTS constant for the facts read

ENABLED = os.environ.get("ORCH_DB_POLICY_SYNTH", "0") == "1"
FINDINGS = "db_findings"

#: column names that, when present on the table, are a tenancy key worth keying a policy on
OWNER_COLS = ("user_id", "owner_id", "account_id", "tenant_id", "profile_id", "org_id",
              "matter_id", "client_id", "created_by", "email")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _qi(name):
    name = str(name or "")
    return ('"%s"' % name) if _IDENT_RE.match(name) else None


def _columns_for(project, table):
    """Latest snapshot's column inventory for one table; [] when unknown. Fail-soft."""
    try:
        rows = db.select(db_chains.SNAPSHOTS, {"select": "facts", "project": "eq.%s" % project,
                                               "order": "taken_at.desc,id.desc", "limit": "1"}) or []
        inv = ((rows[0].get("facts") or {}).get("columns") or {}) if rows else {}
        return list(inv.get(table) or [])
    except Exception as e:
        print("db_policy_synth: column inventory read failed for %s.%s: %s" % (project, table, str(e)[:80]))
        return []


def owner_hint(columns):
    """Best tenancy key: a known owner column wins, then any *_id, then an email."""
    cols = [c for c in (columns or []) if isinstance(c, str) and _IDENT_RE.match(c)]
    for c in cols:
        if c in OWNER_COLS and c != "email":
            return c
    for c in cols:
        if c.endswith("_id"):
            return c
    for c in cols:
        if c == "email" or c.endswith("_email"):
            return c
    return ""


def candidate_policy(project, table, columns=None):
    """(sql, hint) — deny-by-default + a commented owner-keyed policy skeleton — or
    ("", reason) when there is no safe hint at all."""
    qt = _qi(table)
    if not qt:
        return "", "unsafe identifier"
    cols = columns if columns is not None else _columns_for(project, table)
    hint = owner_hint(cols)
    if not hint:
        return "", "no tenancy key on the table (add an owner/tenant column or write the policy by hand)"
    qh = _qi(hint)
    sql = f"""-- db-steering policy candidate for public.{table} — DRAFT, verify before apply.
-- Tenancy hint: column "{hint}" (from the column inventory of the latest scan).
alter table public.{qt} enable row level security;

-- SELECT/UPDATE/DELETE scoped to the row owner; adjust the auth function to your stack
-- (Supabase: auth.uid(); the service role bypasses RLS by design and needs none of this).
-- create policy "read_own"   on public.{qt} for select to authenticated using ({qh}::text = auth.uid()::text);
-- create policy "update_own" on public.{qt} for update to authenticated using ({qh}::text = auth.uid()::text) with check ({qh}::text = auth.uid()::text);
-- create policy "insert_own" on public.{qt} for insert to authenticated with check ({qh}::text = auth.uid()::text);"""
    return sql, hint


def generate_group(project):
    """(candidates, skipped) for the project's open rls_* findings. Deterministic order."""
    try:
        rows = db.select(FINDINGS, {
            "select": "object_name,probe_id", "project": "eq.%s" % project, "status": "eq.open",
            "probe_id": "in.(rls_enabled_no_policy,rls_disabled_tables)",
            "order": "object_name.asc", "limit": "200"}) or []
    except Exception as e:
        print("db_policy_synth: findings read failed for %s: %s" % (project, str(e)[:120]))
        return [], ["read failed: %s" % str(e)[:100]]
    out, skipped, seen = [], [], set()
    for r in rows:
        t = str(r.get("object_name") or "")
        if not t or t in seen:
            continue
        seen.add(t)
        sql, info = candidate_policy(project, t)
        if sql:
            out.append((t, sql, info))
        else:
            skipped.append("%s: %s" % (t, info))
    return out, skipped


def migration_sql(project, candidates):
    header = ("-- db-steering POLICY DESIGN candidates (draft) — every statement here was "
              "generated from column/tenancy hints and needs an engineer's judgment.\n"
              "-- Project: %s · tables: %d\n\nbegin;\n\n" % (project, len(candidates)))
    return header + "\n\n".join(sql for _t, sql, _h in candidates) + "\n\ncommit;\n"
