#!/usr/bin/env python3
"""
db_probes.py — the deterministic, zero-model-cost probe catalog of Database Steering.

WHY A CATALOG. The fleet's only database control used to be one COUNT(*) per app per day.
The catalog below is what "continuously reviewed" means in practice: a few dozen read-only
statements against pg_catalog / information_schema / pg_stat_* (plus Supabase's free advisor
lints) whose rows are turned into FINDINGS by pure Python. NOTHING here calls a model —
that is the cost rule that makes perpetual review affordable (db_steering_contract). Grep
this file for model_gateway / model_policy: there is a unit test asserting it stays clean.

SHAPE OF A PROBE. Each entry of PROBES is a dict:
  id, title, category (CATEGORIES), tier (PROBE_TIERS: cheap every run, medium hourly,
  heavy daily), dialects, evidence_kinds (EVIDENCE_KINDS), sql {dialect: statement},
  parse(rows, source, facts) -> [findings built with make_finding], remediation, plus the
  optional gates requires_capability / requires_fact / providers / advisor_kind.
Every statement is ONE SELECT/WITH, no semicolons, bounded with LIMIT, catalog-only. The
single exception to "never touch user data" is deliberate: there is none. Even the
"orphaned rows" idea is served by the catalog (NOT VALID constraints) instead of a scan.

FACTS. run_all runs probes in list order and hands every parse the same `facts` dict, so a
later probe can be gated on an earlier discovery (`requires_fact`: supabase_migrations
exists, pg_cron installed) and the positive record (table counts, size, extensions,
migrations applied) rides along to the posture snapshot.

FINDINGS ARE EVIDENCE. `direction` matters: most probes report gaps (undermines); several
emit a positive finding when a control is in order (supports) so a legal memo can cite what
is present, not only what is missing. Severity is decided here, deterministically; the memo
engine decides weight. Titles name the object; remediation is concrete and repo-oriented.

ROW TOLERANCE. Rows arrive as JSON (Management API), driver-typed values, or all-strings
from a CLI fallback; Snowflake upper-cases column names. Every parse goes through _v/_num/
_bool/_list so "t", true and "true" agree.
"""
from __future__ import annotations

import concurrent.futures
import inspect
import json
import math
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db_adapters  # noqa: E402
from db_steering_contract import (  # noqa: E402
    CATEGORIES, DIALECTS, EVIDENCE_KINDS, PROBE_TIERS, SEVERITIES, SEVERITY_RANK,
    assert_read_only, make_finding,
)

# Names that suggest a table holds personal data; bumps severity of exposure findings.
PII_TABLE_RE = re.compile(r"user|profile|account|member|customer|client|contact|lead|invoice|payment|message|"
                          r"mail|session|token|auth|address|kyc|document|matter|engagement", re.I)
PII_COLUMN_PATTERN = ("email|phone|ssn|social_security|tax_id|passport|dob|date_of_birth|birth|address|"
                      "ip_address|credit_card|card_number|iban|account_number|password|secret|token")
AUDIT_TABLE_PATTERN = "(_events|_event|_log|_logs|audit|_history|_ledger|_trail|_journal)$"
AI_TABLE_PATTERN = ("model_call|llm_|ai_call|completion|token_usage|usage_log|inference|prompt_log|"
                    "agent_run|counsel_job|job_event")
PRIVILEGED_FUNC_RE = re.compile(r"admin|bypass|service", re.I)
# Edge-function slugs that legitimately skip JWT verification (third-party webhooks, cron).
WEBHOOK_FUNC_RE = re.compile(r"webhook|hook|cron|callback|public", re.I)
SECURITY_INVOKER_RE = re.compile(r"security_invoker\s*=\s*(true|on|1)\b", re.I)
LOCAL_URL_RE = re.compile(r"localhost|127\.0\.0\.1|0\.0\.0\.0", re.I)

# Roles the PLATFORM creates with elevated rights (the Supabase/RDS/Cloud SQL bootstrap
# roles). privileged_login_roles skips them so a project is blamed only for roles it made.
_PLATFORM_ROLES = ("postgres", "supabase_admin", "supabase_auth_admin", "supabase_storage_admin",
                   "supabase_replication_admin", "supabase_read_only_user", "supabase_realtime_admin",
                   "supabase_functions_admin", "supabase_etl_admin", "authenticator", "dashboard_user", "pgbouncer",
                   "rds_superuser", "rdsadmin", "rdsrepladmin", "cloudsqlsuperuser", "cloudsqladmin",
                   "azure_pg_admin", "azuresu", "neon_superuser")
_PLATFORM_ROLES_SQL = "(" + ", ".join("'%s'" % r for r in _PLATFORM_ROLES) + ")"

# Schemas that belong to the platform, not the application. Object-level probes skip them
# so a Supabase project is not blamed for auth.users or storage.objects.
_SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "auth", "storage", "realtime", "supabase_functions",
                   "supabase_migrations", "vault", "extensions", "graphql", "graphql_public", "net",
                   "pgsodium", "pgsodium_masks", "cron", "_realtime", "_analytics", "pgbouncer", "topology",
                   "tiger", "tiger_data", "pgtle", "repack", "pgmq", "supabase_admin")
_SYS_SQL = "(" + ", ".join("'%s'" % s for s in _SYSTEM_SCHEMAS) + ")"


def _user_schema(col):
    return f"{col} not in {_SYS_SQL} and {col} not like 'pg\\_toast%' and {col} not like 'pg\\_temp%'"


def _log(msg):
    print(f"db_probes: {msg}")


# ── row helpers ────────────────────────────────────────────────────────────────────────

def _v(row, *keys, default=None):
    if not isinstance(row, dict):
        return default
    for k in keys:
        for kk in (k, k.upper(), k.lower()):
            if kk in row and row[kk] is not None:
                return row[kk]
    return default


def _num(v, default=0.0) -> float:
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return v != 0
    return str(v).strip().lower() in ("t", "true", "1", "yes", "y", "on")


def _list(v) -> list:
    if v is None:
        return []
    if isinstance(v, (list, tuple, set)):
        return [str(x) for x in v]
    s = str(v).strip()
    if s.startswith("[") and s.endswith("]"):
        try:
            return [str(x) for x in json.loads(s)]
        except ValueError:
            pass
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    return [p.strip().strip('"') for p in s.split(",") if p.strip()]


def _s(v) -> str:
    return "" if v is None else str(v)


def _obj(row):
    return _s(_v(row, "schemaname", "table_schema", default="")), _s(_v(row, "tablename", "table_name", default=""))


def _names(rows, cap=30):
    names = [".".join(x for x in _obj(r) if x) for r in rows]
    shown = ", ".join(names[:cap])
    if len(names) > cap:
        shown += f" (+{len(names) - cap} more)"
    return shown


# ── parse functions (pure; rows in, findings out) ──────────────────────────────────────

def _p_rls_disabled(rows, source, facts=None):
    facts = facts if facts is not None else {}
    off = [r for r in rows if not _bool(_v(r, "rowsecurity"))]
    facts["public_tables"] = len(rows)
    facts["rls_off_tables"] = len(off)
    out = []
    if rows and not off:
        out.append(make_finding("rls_disabled_tables", "security", "info",
                                f"All {len(rows)} public tables enforce RLS", direction="supports",
                                evidence_kinds=("access_control",), extra="all_rls",
                                metrics={"tables": len(rows)}, detail="rowsecurity is true on every public table."))
    for r in off:
        schema, table = _obj(r)
        sev = "high" if PII_TABLE_RE.search(table) else "medium"
        out.append(make_finding("rls_disabled_tables", "security", sev, f"RLS disabled on {schema}.{table}",
                                object_schema=schema, object_name=table, evidence_kinds=("access_control",),
                                detail=("Table name suggests personal data; every row is readable by any role "
                                        "with a SELECT grant (anon key included)." if sev == "high" else
                                        "Every row is readable by any role with a SELECT grant."),
                                metrics={"pii_name": sev == "high"}))
    return out


def _p_rls_no_policy(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        out.append(make_finding("rls_enabled_no_policy", "security", "medium",
                                f"RLS enabled but no policies on {schema}.{table}", object_schema=schema,
                                object_name=table, evidence_kinds=("access_control",),
                                detail="With RLS on and zero policies the table is invisible to every non-owner "
                                       "role: either the app cannot use it or a service role bypasses RLS entirely."))
    return out


def _p_anon_grants(rows, source, facts=None):
    by_key = {}
    for r in rows:
        schema, table = _obj(r)
        grantee = _s(_v(r, "grantee"))
        priv = _s(_v(r, "privilege_type")).upper()
        rls = _bool(_v(r, "rowsecurity", default=True))
        k = (schema, table, grantee)
        by_key.setdefault(k, {"privs": set(), "rls": rls})["privs"].add(priv)
    out = []
    for (schema, table, grantee), info in sorted(by_key.items()):
        privs = sorted(info["privs"])
        writes = [p for p in privs if p in ("INSERT", "UPDATE", "DELETE")]
        pii = bool(PII_TABLE_RE.search(table))
        if writes:
            sev = "high"
        elif "SELECT" in privs and pii:
            sev = "high"
        else:
            sev = "low"
        # RLS gates a grant; the grant alone is then a policy question, one notch lower.
        if info["rls"] and sev == "high":
            sev = "medium"
        kinds = ("access_control", "data_minimization") if pii or "SELECT" in privs else ("access_control",)
        out.append(make_finding("anon_or_public_grants", "security", sev,
                                f"{grantee} holds {', '.join(privs)} on {schema}.{table}", object_schema=schema,
                                object_name=table, extra=grantee, evidence_kinds=kinds,
                                metrics={"privileges": privs, "rowsecurity": info["rls"], "pii_name": pii},
                                detail=(f"Grants to {grantee}: {', '.join(privs)}; RLS "
                                        f"{'on (policies decide)' if info['rls'] else 'OFF — grant is unconditional'}.")))
    return out


def _p_no_pk(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        est = max(0.0, _num(_v(r, "est_rows")))
        sev = "high" if est > 10000 else "medium"
        out.append(make_finding("tables_without_primary_key", "integrity", sev, f"No primary key on {schema}.{table}",
                                object_schema=schema, object_name=table, evidence_kinds=("integrity",),
                                metrics={"est_rows": int(est)},
                                detail=f"~{int(est)} rows; without a key rows cannot be addressed, deduplicated or replicated."))
    return out


def _p_unindexed_fk(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        con = _s(_v(r, "conname"))
        ref_rows = max(0.0, _num(_v(r, "referenced_rows")))
        sev = "high" if ref_rows > 100000 else "medium"
        cols = [str(c) for c in _list(_v(r, "fk_columns")) if str(c or "").strip()]
        out.append(make_finding("unindexed_foreign_keys", "performance", sev,
                                f"Foreign key {con} on {schema}.{table} has no covering index", object_schema=schema,
                                object_name=table, extra=con, evidence_kinds=("availability", "integrity"),
                                metrics={"constraint": con, "referenced_table": _s(_v(r, "referenced_table")),
                                         "columns": cols,
                                         "referenced_rows": int(ref_rows), "est_rows": int(max(0.0, _num(_v(r, "est_rows"))))},
                                detail="Deletes/updates on the referenced table scan this table; joins on the key do too."))
    return out


def _p_unused_indexes(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        idx = _s(_v(r, "indexname"))
        size = _num(_v(r, "index_bytes"))
        sev = "medium" if size > 100 * 1024 * 1024 else "low"
        out.append(make_finding("unused_indexes", "cost", sev, f"Index {idx} on {schema}.{table} is never scanned",
                                object_schema=schema, object_name=table, extra=idx, evidence_kinds=("availability",),
                                metrics={"index": idx, "index_bytes": int(size), "idx_scan": int(_num(_v(r, "idx_scan")))},
                                detail=f"{int(size / 1048576)} MB maintained on every write, read by no query since stats reset."))
    return out


def _p_duplicate_indexes(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        idxs = _list(_v(r, "indexes"))
        out.append(make_finding("duplicate_indexes", "cost", "low",
                                f"Duplicate indexes on {schema}.{table}: {', '.join(idxs)}", object_schema=schema,
                                object_name=table, extra=",".join(sorted(idxs)), evidence_kinds=("availability",),
                                metrics={"indexes": idxs}, detail="Identical key columns and operator classes."))
    return out


def _p_dead_tuples(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        live, dead = _num(_v(r, "n_live_tup")), _num(_v(r, "n_dead_tup"))
        ratio = dead / max(live, 1.0)
        sev = "high" if ratio > 0.5 else "medium"
        out.append(make_finding("dead_tuple_bloat", "availability", sev, f"Dead-tuple bloat on {schema}.{table}",
                                object_schema=schema, object_name=table, evidence_kinds=("availability",),
                                metrics={"n_live_tup": int(live), "n_dead_tup": int(dead), "ratio": round(ratio, 3),
                                         "last_autovacuum": _s(_v(r, "last_autovacuum"))},
                                detail=f"{int(dead)} dead vs {int(live)} live tuples ({ratio:.0%})."))
    return out


def _p_vacuum_stale(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        last = _v(r, "last_autovacuum")
        sev = "medium" if last in (None, "") else "low"
        out.append(make_finding("vacuum_stale", "availability", sev,
                                f"Autovacuum {'never ran' if sev == 'medium' else 'stale (>7d)'} on {schema}.{table}",
                                object_schema=schema, object_name=table, evidence_kinds=("availability",),
                                metrics={"n_live_tup": int(_num(_v(r, "n_live_tup"))), "last_autovacuum": _s(last)}))
    return out


def _p_sequence_headroom(rows, source, facts=None):
    out = []
    for r in rows:
        schema = _s(_v(r, "schemaname"))
        seq = _s(_v(r, "sequencename"))
        ratio = _num(_v(r, "used_ratio"))
        if ratio <= 0.6:
            continue
        sev = "critical" if ratio > 0.85 else "medium"
        out.append(make_finding("sequence_headroom", "availability", sev,
                                f"Sequence {schema}.{seq} is {ratio:.0%} consumed", object_schema=schema,
                                object_name=seq, evidence_kinds=("availability",),
                                metrics={"used_ratio": round(ratio, 4), "last_value": _s(_v(r, "last_value")),
                                         "max_value": _s(_v(r, "max_value"))},
                                detail="When it wraps, every insert on the owning table fails."))
    return out


def _p_slow_queries(rows, source, facts=None):
    out = []
    for r in rows:
        qid = _s(_v(r, "queryid"))
        mean = _num(_v(r, "mean_exec_time"))
        calls = _num(_v(r, "calls"))
        total = _num(_v(r, "total_exec_time"))
        sev = "high" if mean > 2000 else "medium"
        text = _s(_v(r, "query"))[:200]
        out.append(make_finding("slow_query_classes", "performance", sev,
                                f"Query class {qid}: mean {mean:.0f} ms over {int(calls)} calls", extra=qid,
                                evidence_kinds=("availability",), detail=text,
                                metrics={"queryid": qid, "calls": int(calls), "mean_exec_ms": round(mean, 1),
                                         "total_exec_ms": round(total, 1)}))
    return out


def _p_missing_audit(rows, source, facts=None):
    facts = facts if facts is not None else {}
    out = []
    missing = 0
    for r in rows:
        schema, table = _obj(r)
        has_created = _bool(_v(r, "has_created"))
        has_updated = _bool(_v(r, "has_updated"))
        has_upd_grants = _bool(_v(r, "has_update_grants"))
        if not has_created:
            missing += 1
            out.append(make_finding("missing_audit_columns", "audit", "medium",
                                    f"No created_at/inserted_at on {schema}.{table}", object_schema=schema,
                                    object_name=table, evidence_kinds=("audit_trail",),
                                    metrics={"missing": ["created_at"] + ([] if has_updated else ["updated_at"])},
                                    detail="Rows cannot be shown to have been recorded contemporaneously."))
        elif not has_updated and has_upd_grants:
            out.append(make_finding("missing_audit_columns", "audit", "low",
                                    f"Updatable table {schema}.{table} has created_at but no updated_at",
                                    object_schema=schema, object_name=table, evidence_kinds=("audit_trail",),
                                    metrics={"missing": ["updated_at"]},
                                    detail="UPDATE is granted to non-owner roles yet modifications leave no timestamp."))
    facts["tables_missing_created_at"] = missing
    if rows and missing == 0:
        out.append(make_finding("missing_audit_columns", "audit", "info",
                                f"All {len(rows)} public tables carry a creation timestamp", direction="supports",
                                evidence_kinds=("audit_trail",), extra="all_created", metrics={"tables": len(rows)}))
    return out


def _p_audit_trail(rows, source, facts=None):
    facts = facts if facts is not None else {}
    names = [".".join(x for x in _obj(r) if x) for r in rows]
    facts["audit_tables"] = names[:100]
    if names:
        return [make_finding("audit_trail_presence", "audit", "info",
                             f"{len(names)} audit/event tables present", direction="supports",
                             evidence_kinds=("audit_trail",), extra="presence", detail=_names(rows),
                             metrics={"count": len(names), "tables": names[:30]})]
    return [make_finding("audit_trail_presence", "audit", "medium", "No audit/event/log tables found in public",
                         evidence_kinds=("audit_trail",), extra="presence",
                         detail="No table name matches *_events, *_log(s), *audit*, *_history, *_ledger, *_trail.")]


def _p_pii_inventory(rows, source, facts=None):
    facts = facts if facts is not None else {}
    out = []
    facts["pii_tables"] = len(rows)
    for r in rows:
        schema, table = _obj(r)
        cols = _list(_v(r, "columns"))
        out.append(make_finding("pii_columns_inventory", "privacy", "info",
                                f"{schema}.{table} holds personal-data columns: {', '.join(cols[:12])}",
                                direction="supports", object_schema=schema, object_name=table,
                                evidence_kinds=("data_minimization",), metrics={"columns": cols},
                                detail="Inventory entry; exposure is assessed by pii_exposed_tables and grants probes."))
    return out


def _p_pii_exposed(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        cols = _list(_v(r, "columns"))
        out.append(make_finding("pii_exposed_tables", "privacy", "high",
                                f"Personal data in {schema}.{table} with RLS off ({', '.join(cols[:8])})",
                                object_schema=schema, object_name=table,
                                evidence_kinds=("data_minimization", "access_control"), metrics={"columns": cols},
                                detail="Columns look like personal data and rowsecurity is false: any granted role reads every row."))
    return out


def _p_soft_delete(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        out.append(make_finding("soft_delete_without_purge", "retention", "low",
                                f"{schema}.{table} soft-deletes (deleted_at); verify a purge job exists",
                                object_schema=schema, object_name=table, evidence_kinds=("retention",),
                                detail="Soft-deleted rows persist indefinitely unless a scheduled purge removes them."))
    return out


def _p_cron_jobs(rows, source, facts=None):
    facts = facts if facts is not None else {}
    names = [_s(_v(r, "jobname")) or f"job {_s(_v(r, 'jobid'))}" for r in rows]
    facts["cron_jobs"] = names[:100]
    if not rows:
        return [make_finding("pg_cron_jobs", "retention", "low", "pg_cron installed but no jobs scheduled",
                             evidence_kinds=("retention",), extra="jobs")]
    return [make_finding("pg_cron_jobs", "retention", "info", f"{len(rows)} pg_cron jobs scheduled",
                         direction="supports", evidence_kinds=("retention", "availability"), extra="jobs",
                         detail=", ".join(f"{n} [{_s(_v(r, 'schedule'))}]" for n, r in zip(names[:30], rows[:30])),
                         metrics={"jobs": names[:30]})]


def _p_secdef_functions(rows, source, facts=None):
    out = []
    for r in rows:
        schema = _s(_v(r, "schemaname"))
        fn = _s(_v(r, "funcname"))
        sig = _s(_v(r, "signature")) or fn
        sev = "medium" if PRIVILEGED_FUNC_RE.search(fn) else "low"
        out.append(make_finding("security_definer_functions", "security", sev,
                                f"Definer-rights function {schema}.{sig}", object_schema=schema, object_name=fn,
                                extra=sig, evidence_kinds=("access_control",),
                                detail="Runs with its owner's privileges regardless of caller; bypasses RLS unless it re-checks."))
    return out


def _p_extensions(rows, source, facts=None):
    facts = facts if facts is not None else {}
    names = sorted({_s(_v(r, "extname")) for r in rows} - {""})
    facts["extensions"] = names
    facts["has_pg_cron"] = "pg_cron" in names
    facts["has_pg_stat_statements"] = "pg_stat_statements" in names
    out = []
    for r in rows:
        ext = _s(_v(r, "extname"))
        schema = _s(_v(r, "schemaname"))
        if schema == "public" and ext not in ("plpgsql",):
            out.append(make_finding("extensions_in_public", "schema_drift", "low",
                                    f"Extension {ext} installed in schema public", object_schema="public",
                                    object_name=ext, evidence_kinds=("change_control",),
                                    metrics={"version": _s(_v(r, "extversion"))}))
    return out


def _p_migrations_state(rows, source, facts=None):
    facts = facts if facts is not None else {}
    n = _num(_v(rows[0], "n")) if rows else 0.0
    facts["has_schema_migrations"] = n > 0
    if n > 0 or str((source or {}).get("provider")) != "supabase":
        return []
    return [make_finding("schema_migrations_state", "schema_drift", "low",
                         "No supabase_migrations.schema_migrations table", evidence_kinds=("change_control",),
                         extra="absent", detail="Schema changes cannot be attributed to a versioned migration.")]


def _p_migrations_latest(rows, source, facts=None):
    facts = facts if facts is not None else {}
    row = rows[0] if rows else {}
    n = int(_num(_v(row, "n")))
    latest = _s(_v(row, "latest"))
    facts["migrations_applied"] = n
    facts["latest_migration"] = latest
    return [make_finding("schema_migrations_latest", "schema_drift", "info",
                         f"{n} migrations applied, latest {latest or '(none)'}", direction="supports",
                         evidence_kinds=("change_control",), extra="latest",
                         metrics={"applied": n, "latest": latest})]


def _p_ai_logging(rows, source, facts=None):
    facts = facts if facts is not None else {}
    names = [".".join(x for x in _obj(r) if x) for r in rows]
    facts["ai_log_tables"] = names[:100]
    if names:
        return [make_finding("ai_call_logging_presence", "ai_governance", "info",
                             f"{len(names)} model-call/usage log tables present", direction="supports",
                             evidence_kinds=("ai_logging", "audit_trail"), extra="presence", detail=_names(rows),
                             metrics={"tables": names[:30]})]
    return [make_finding("ai_call_logging_presence", "ai_governance", "medium",
                         "No model-call / token-usage log table found", evidence_kinds=("ai_logging",), extra="presence",
                         detail="If this project calls models, no table records model, route, cost or time per call.")]


def _p_unvalidated(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        con = _s(_v(r, "conname"))
        out.append(make_finding("unvalidated_constraints", "integrity", "medium",
                                f"Constraint {con} on {schema}.{table} is NOT VALID", object_schema=schema,
                                object_name=table, extra=con, evidence_kinds=("integrity",),
                                metrics={"contype": _s(_v(r, "contype"))},
                                detail="Existing rows were never checked against it; orphans or violations may already exist."))
    return out


def _p_inventory(rows, source, facts=None):
    facts = facts if facts is not None else {}
    row = rows[0] if rows else {}
    tables = int(_num(_v(row, "tables")))
    views = int(_num(_v(row, "views")))
    matviews = int(_num(_v(row, "matviews")))
    functions = int(_num(_v(row, "functions")))
    size = int(_num(_v(row, "db_size_bytes")))
    pretty = _s(_v(row, "db_size")) or f"{size / 1048576:.0f} MB"
    facts.update({"tables": tables, "views": views, "matviews": matviews, "functions": functions,
                  "db_size_bytes": size, "database": _s(_v(row, "dbname"))})
    return [make_finding("table_inventory_facts", "availability", "info",
                         f"{tables} tables, {views} views, {matviews} materialized views, {functions} functions, {pretty}",
                         direction="supports", evidence_kinds=("availability",), extra="inventory",
                         metrics={"tables": tables, "views": views, "matviews": matviews, "functions": functions,
                                  "db_size_bytes": size})]


def _p_fk_graph(rows, source, facts=None):
    """Facts-only: the FK edge list db_chains computes blast radius from. Emits nothing."""
    facts = facts if facts is not None else {}
    edges = []
    for r in rows:
        child = _s(_v(r, "child_table"))
        parent = _s(_v(r, "parent_table"))
        if not child or not parent:
            continue
        edges.append({"child": child, "parent": parent,
                      "columns": [str(x) for x in _list(_v(r, "fk_columns"))]})
    facts["fk_edges"] = edges[:1000]
    return []


def _p_columns(rows, source, facts=None):
    """Facts-only: {table: [columns]} — policy synthesis detects owner/tenant columns here."""
    facts = facts if facts is not None else {}
    inv = {}
    for r in rows:
        t = _s(_v(r, "tablename"))
        if t:
            inv[t] = [str(x) for x in _list(_v(r, "columns"))][:200]
    facts["columns"] = inv
    return []


def _p_long_txns(rows, source, facts=None):
    out = []
    for r in rows:
        pid = _s(_v(r, "pid"))
        age = _num(_v(r, "xact_age_s"))
        out.append(make_finding("long_running_transactions", "availability", "medium",
                                f"Transaction open {int(age // 60)} min (pid {pid}, {_s(_v(r, 'usename'))})", extra=pid,
                                evidence_kinds=("availability",),
                                metrics={"pid": pid, "age_s": int(age), "state": _s(_v(r, "state")),
                                         "verb": _s(_v(r, "verb")), "application": _s(_v(r, "application_name"))},
                                detail="Holds locks and blocks vacuum from reclaiming rows for as long as it stays open."))
    return out


def _p_ts_without_tz(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        cols = _list(_v(r, "columns"))
        out.append(make_finding("timestamp_without_timezone", "integrity", "low",
                                f"{schema}.{table} uses timestamp without time zone: {', '.join(cols[:10])}",
                                object_schema=schema, object_name=table, evidence_kinds=("integrity",),
                                metrics={"columns": cols}))
    return out


def _p_text_keys(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        col = _s(_v(r, "column_name"))
        out.append(make_finding("uuid_text_keys", "integrity", "low",
                                f"Text-typed key column {col} on {schema}.{table}", object_schema=schema,
                                object_name=table, extra=col, evidence_kinds=("integrity",),
                                detail="A text key accepts anything; uuid/bigint keys reject malformed identifiers."))
    return out


def _p_bq_partition(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        size = _num(_v(r, "size_bytes"))
        out.append(make_finding("partition_or_cluster_missing", "cost", "medium",
                                f"{schema}.{table} ({size / 1073741824:.1f} GB) is neither partitioned nor clustered",
                                object_schema=schema, object_name=table, evidence_kinds=("availability",),
                                metrics={"size_bytes": int(size), "row_count": int(_num(_v(r, "row_count")))},
                                detail="Every query scans the full table and is billed for it."))
    return out


def _p_privileged_roles(rows, source, facts=None):
    out = []
    for r in rows:
        role = _s(_v(r, "rolname"))
        sup = _bool(_v(r, "rolsuper"))
        bypass = _bool(_v(r, "rolbypassrls"))
        what = "a superuser" if sup else "exempt from RLS (bypassrls)"
        out.append(make_finding("privileged_login_roles", "security", "high" if sup else "medium",
                                f"Login role {role} is {what}", object_name=role, evidence_kinds=("access_control",),
                                metrics={"rolsuper": sup, "rolbypassrls": bypass,
                                         "rolcreaterole": _bool(_v(r, "rolcreaterole")),
                                         "rolreplication": _bool(_v(r, "rolreplication")),
                                         "valid_until": _s(_v(r, "rolvaliduntil"))},
                                detail=("A leaked credential for this role reads and writes every row of every table; "
                                        "RLS and grants do not apply." if sup else
                                        "A leaked credential for this role reads every row regardless of policy.")))
    return out


def _p_invalid_indexes(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        idx = _s(_v(r, "indexname"))
        unique = _bool(_v(r, "indisunique"))
        out.append(make_finding("invalid_indexes", "integrity", "high" if unique else "medium",
                                f"Invalid index {idx} on {schema}.{table}", object_schema=schema, object_name=table,
                                extra=idx, evidence_kinds=("integrity", "availability"),
                                metrics={"index": idx, "indisunique": unique,
                                         "index_bytes": int(_num(_v(r, "index_bytes")))},
                                detail=("Left behind by a failed or interrupted concurrent build: the planner never uses "
                                        "it, every write still maintains it"
                                        + (", and the uniqueness it promises is NOT enforced." if unique else "."))))
    return out


def _p_cascade_blast_radius(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        con = _s(_v(r, "conname"))
        est = int(max(0.0, _num(_v(r, "est_rows"))))
        parent = ".".join(x for x in (_s(_v(r, "referenced_schema")), _s(_v(r, "referenced_table"))) if x)
        sev = "high" if est > 1000000 else "medium"
        out.append(make_finding("cascade_delete_blast_radius", "integrity", sev,
                                f"Deleting from {parent} cascades into {schema}.{table} (~{est} rows) via {con}",
                                object_schema=schema, object_name=table, extra=con, evidence_kinds=("integrity",),
                                metrics={"constraint": con, "referenced_table": parent, "est_rows": est,
                                         "referenced_rows": int(max(0.0, _num(_v(r, "referenced_rows"))))},
                                detail="One DELETE on the parent silently removes dependent rows here with no audit row "
                                       "and no confirmation; a bug or an over-broad policy becomes data loss."))
    return out


def _p_disabled_triggers(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        trg = _s(_v(r, "triggername"))
        internal = _bool(_v(r, "tgisinternal"))
        out.append(make_finding("disabled_triggers", "integrity", "high" if internal else "medium",
                                f"Trigger {trg} disabled on {schema}.{table}", object_schema=schema, object_name=table,
                                extra=trg, evidence_kinds=("integrity",) if internal else ("integrity", "audit_trail"),
                                metrics={"trigger": trg, "tgisinternal": internal, "tgenabled": _s(_v(r, "tgenabled"))},
                                detail=("A constraint trigger is off (DISABLE TRIGGER ALL?): the foreign key it enforces "
                                        "accepts orphans until it is re-enabled." if internal else
                                        "Whatever the trigger maintained (timestamps, audit rows, denormalised counts) "
                                        "has not been maintained since it was disabled.")))
    return out


def _p_large_no_index(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        est = int(max(0.0, _num(_v(r, "est_rows"))))
        size = int(_num(_v(r, "total_bytes")))
        out.append(make_finding("large_tables_without_index", "performance", "high",
                                f"{schema}.{table} (~{est} rows) has no index at all", object_schema=schema,
                                object_name=table, evidence_kinds=("availability",),
                                metrics={"est_rows": est, "total_bytes": size},
                                detail=f"{size // 1048576} MB; every lookup, join and delete is a full sequential scan."))
    return out


def _p_views_over_rls(rows, source, facts=None):
    out = []
    for r in rows:
        schema = _s(_v(r, "schemaname"))
        view = _s(_v(r, "viewname"))
        kind = _s(_v(r, "relkind"))
        if kind == "v" and SECURITY_INVOKER_RE.search(_s(_v(r, "reloptions"))):
            continue  # runs as the caller: the base tables' policies still apply
        grantees = sorted(set(_list(_v(r, "grantees"))))
        bases = sorted(set(_list(_v(r, "base_tables"))))
        pii = any(PII_TABLE_RE.search(b.split(".")[-1]) for b in bases)
        label = "Materialized view" if kind == "m" else "View"
        out.append(make_finding("views_exposed_over_rls_tables", "security", "high" if pii else "medium",
                                f"{label} {schema}.{view} exposes RLS-protected {', '.join(bases[:6])} to {', '.join(grantees)}",
                                object_schema=schema, object_name=view,
                                evidence_kinds=("access_control", "data_minimization") if pii else ("access_control",),
                                metrics={"relkind": kind, "grantees": grantees, "base_tables": bases, "pii_name": pii},
                                detail=("A materialized view stores its own copy of the rows; the base tables' policies "
                                        "never run against it." if kind == "m" else
                                        "The view runs with its owner's privileges (no security_invoker), so the base "
                                        "tables' policies do not apply to callers of the view.")))
    return out


def _p_pii_anon(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        cols = _list(_v(r, "columns"))
        rls = _bool(_v(r, "rowsecurity", default=True))
        grantees = sorted(set(_list(_v(r, "grantees"))))
        out.append(make_finding("pii_readable_by_anon", "privacy", "medium" if rls else "critical",
                                f"Plain-text personal data in {schema}.{table} is granted to {', '.join(grantees) or 'anon'} "
                                f"({', '.join(cols[:8])})", object_schema=schema, object_name=table,
                                evidence_kinds=("data_minimization", "access_control"),
                                metrics={"columns": cols, "rowsecurity": rls, "grantees": grantees},
                                detail=("RLS is OFF: anyone holding the public anon key reads every row of these columns."
                                        if not rls else
                                        "RLS is on, so policies decide — but the anon grant means one permissive policy "
                                        "exposes these columns to the internet.")))
    return out


def _p_updated_at_no_trigger(rows, source, facts=None):
    out = []
    for r in rows:
        schema, table = _obj(r)
        out.append(make_finding("updated_at_without_trigger", "audit", "low",
                                f"{schema}.{table} has updated_at but no trigger maintains it", object_schema=schema,
                                object_name=table, evidence_kinds=("audit_trail",),
                                detail="No UPDATE trigger fires on the table, so the column is only as accurate as every "
                                       "code path that remembers to set it; a modification timestamp that can be stale "
                                       "is weak evidence of when a record last changed."))
    return out


def _p_idle_in_txn(rows, source, facts=None):
    out = []
    for r in rows:
        pid = _s(_v(r, "pid"))
        idle = _num(_v(r, "idle_s"))
        state = _s(_v(r, "state"))
        sev = "high" if idle > 1800 or "aborted" in state.lower() else "medium"
        out.append(make_finding("idle_in_transaction_sessions", "availability", sev,
                                f"Session idle in transaction for {int(idle // 60)} min (pid {pid}, {_s(_v(r, 'usename'))})",
                                extra=pid, evidence_kinds=("availability",),
                                metrics={"pid": pid, "idle_s": int(idle), "xact_age_s": int(_num(_v(r, "xact_age_s"))),
                                         "state": state, "application": _s(_v(r, "application_name"))},
                                detail="A client opened a transaction, stopped talking and never committed: its locks "
                                       "block DDL and writers, and vacuum cannot reclaim anything newer than it."))
    return out


def _p_connection_saturation(rows, source, facts=None):
    facts = facts if facts is not None else {}
    row = rows[0] if rows else None
    if not isinstance(row, dict):
        return []
    total = int(_num(_v(row, "connections")))
    limit = int(_num(_v(row, "max_connections")))
    if limit <= 0:
        return []
    ratio = total / float(limit)
    facts["connections"] = total
    facts["max_connections"] = limit
    metrics = {"connections": total, "active": int(_num(_v(row, "active"))), "max_connections": limit,
               "ratio": round(ratio, 3)}
    if ratio >= 0.8:
        return [make_finding("connection_saturation", "availability", "critical" if ratio >= 0.9 else "high",
                             f"Connections at {ratio:.0%} of max_connections ({total}/{limit})", extra="usage",
                             evidence_kinds=("availability",), metrics=metrics,
                             detail="When the limit is hit every new client (including this review) is refused; "
                                    "a leaked pool or a traffic spike turns into an outage.")]
    return [make_finding("connection_saturation", "availability", "info",
                         f"Connections at {ratio:.0%} of max_connections ({total}/{limit})", direction="supports",
                         extra="usage", evidence_kinds=("availability",), metrics=metrics)]


def _p_replication_slots(rows, source, facts=None):
    out = []
    for r in rows:
        slot = _s(_v(r, "slot_name"))
        active = _bool(_v(r, "active"))
        retained = max(0.0, _num(_v(r, "retained_bytes")))
        gb = retained / 1073741824.0
        if active and gb <= 1.0:
            continue  # healthy: consumer connected and close to the head of the WAL
        if not active:
            sev, what = "high", "inactive"
        else:
            sev, what = ("high" if gb > 10.0 else "medium"), "lagging"
        out.append(make_finding("replication_slots_lagging", "availability", sev,
                                f"Replication slot {slot} is {what}, {gb:.1f} GB of WAL retained", object_name=slot,
                                evidence_kinds=("availability",),
                                metrics={"slot": slot, "slot_type": _s(_v(r, "slot_type")), "active": active,
                                         "retained_bytes": int(retained), "database": _s(_v(r, "database"))},
                                detail=("No consumer is connected; the server keeps every WAL segment since the slot's "
                                        "position until the disk fills." if not active else
                                        "The consumer is far behind; WAL accumulates and vacuum cannot advance past it.")))
    return out


def _p_storage_buckets(rows, source, facts=None):
    facts = facts if facts is not None else {}
    out = []
    public = [r for r in rows if _bool(_v(r, "public"))]
    facts["storage_buckets"] = len(rows)
    facts["public_storage_buckets"] = len(public)
    if rows and not public:
        out.append(make_finding("public_storage_buckets", "security", "info",
                                f"All {len(rows)} storage buckets are private", direction="supports",
                                evidence_kinds=("access_control",), extra="all_private", object_schema="storage",
                                metrics={"buckets": len(rows)}))
    for r in public:
        name = _s(_v(r, "name")) or _s(_v(r, "id"))
        pii = bool(PII_TABLE_RE.search(name))
        out.append(make_finding("public_storage_buckets", "security", "high" if pii else "medium",
                                f"Storage bucket {name} is public", object_schema="storage", object_name=name,
                                evidence_kinds=("access_control", "data_minimization") if pii else ("access_control",),
                                metrics={"bucket": name, "pii_name": pii,
                                         "file_size_limit": _s(_v(r, "file_size_limit"))},
                                detail="Every object in it is readable by URL without a token, RLS policies notwithstanding."))
    return out


# ── Supabase Management API config probes ─────────────────────────────────────────────
# ENGINE CONTRACT. A probe carrying `config_path` (one path or a list) has NO SQL. run_probe
# calls db_adapters.supabase_config(source, path) for each path and hands the parser
#     rows = [{path: payload, ...}]           — ONE dict element, one key per path
# where payload is the parsed JSON the Management API returned for
# GET https://api.supabase.com/v1/projects/{ref}{path}. A parser never sees a token.

def _cfg(rows, path):
    """The payload a config probe received for `path`, or None (missing / wrong shape)."""
    want = str(path or "").strip("/")
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        for k, v in r.items():
            if str(k).strip("/") == want:
                return v
    return None


def _p_auth_config(rows, source, facts=None):
    cfg = _cfg(rows, "/config/auth")
    if not isinstance(cfg, dict):
        return []
    out = []
    reviewed = []

    def flag(key, sev, title, detail, value):
        out.append(make_finding("supabase_auth_config", "security", sev, title, object_schema="auth", object_name=key,
                                extra=key, evidence_kinds=("access_control",), metrics={key: value}, detail=detail))

    def has(key):
        if key in cfg and cfg.get(key) is not None:
            reviewed.append(key)
            return True
        return False

    if has("password_min_length"):
        n = int(_num(cfg["password_min_length"]))
        if n < 8:
            flag("password_min_length", "medium" if n < 6 else "low", f"Minimum password length is {n}",
                 "Below the 8-character floor every current guideline sets; short passwords fall to online guessing.", n)
    if has("mailer_autoconfirm") and _bool(cfg["mailer_autoconfirm"]):
        flag("mailer_autoconfirm", "medium", "Email confirmation is disabled (mailer_autoconfirm)",
             "Accounts are created for any address without proving control of it; anyone can register as anyone.", True)
    if has("sms_autoconfirm") and _bool(cfg["sms_autoconfirm"]):
        flag("sms_autoconfirm", "low", "Phone confirmation is disabled (sms_autoconfirm)",
             "Phone numbers are accepted unverified.", True)
    if has("external_anonymous_users_enabled") and _bool(cfg["external_anonymous_users_enabled"]):
        flag("external_anonymous_users_enabled", "medium", "Anonymous sign-ins are enabled",
             "Any visitor can mint an `authenticated` session; every policy written for authenticated users applies to them.",
             True)
    if has("security_captcha_enabled") and not _bool(cfg["security_captcha_enabled"]):
        flag("security_captcha_enabled", "low", "Captcha protection is off for auth endpoints",
             "Sign-up, sign-in and password-reset endpoints accept unlimited scripted attempts.", False)
    if has("jwt_exp"):
        exp = int(_num(cfg["jwt_exp"]))
        if exp > 86400:
            flag("jwt_exp", "medium", f"Access tokens live {exp // 3600} hours (jwt_exp)",
                 "A stolen access token stays valid for that long; revocation only takes effect at refresh.", exp)
    if has("security_manual_linking_enabled") and _bool(cfg["security_manual_linking_enabled"]):
        flag("security_manual_linking_enabled", "low", "Manual identity linking is enabled",
             "Clients may link identities to a user themselves; account-takeover paths must be reviewed in the app.", True)
    if has("security_update_password_require_reauthentication") and \
            not _bool(cfg["security_update_password_require_reauthentication"]):
        flag("security_update_password_require_reauthentication", "low",
             "Password changes do not require re-authentication",
             "A hijacked session can set a new password without knowing the old one.", False)
    if has("refresh_token_rotation_enabled") and not _bool(cfg["refresh_token_rotation_enabled"]):
        flag("refresh_token_rotation_enabled", "low", "Refresh token rotation is off",
             "A stolen refresh token stays usable indefinitely instead of being invalidated on first reuse.", False)
    if has("site_url"):
        site = _s(cfg["site_url"])
        if LOCAL_URL_RE.search(site):
            flag("site_url", "medium", f"Auth site_url points at {site}",
                 "Confirmation and recovery links redirect users to a local address; production mail is broken or "
                 "the project is a dev configuration serving real users.", site)
    if not out and reviewed:
        out.append(make_finding("supabase_auth_config", "security", "info",
                                f"Auth configuration: no weaknesses in {len(reviewed)} reviewed settings",
                                direction="supports", object_schema="auth", extra="all_ok",
                                evidence_kinds=("access_control",), metrics={"reviewed": reviewed}))
    return out


def _p_backups(rows, source, facts=None):
    cfg = _cfg(rows, "/database/backups")
    if not isinstance(cfg, dict):
        return []
    facts = facts if facts is not None else {}
    pitr = _bool(_v(cfg, "pitr_enabled"))
    walg = _bool(_v(cfg, "walg_enabled"))
    backups = cfg.get("backups")
    n_backups = len(backups) if isinstance(backups, list) else 0
    facts["pitr_enabled"] = pitr
    facts["backups_on_file"] = n_backups
    out = []
    if pitr:
        out.append(make_finding("supabase_backups_pitr", "availability", "info", "Point-in-time recovery is enabled",
                                direction="supports", extra="pitr", evidence_kinds=("availability",),
                                metrics={"pitr_enabled": True, "walg_enabled": walg, "backups": n_backups}))
    else:
        out.append(make_finding("supabase_backups_pitr", "availability", "medium", "Point-in-time recovery is disabled",
                                extra="pitr", evidence_kinds=("availability",),
                                metrics={"pitr_enabled": False, "walg_enabled": walg, "backups": n_backups},
                                detail="Recovery is limited to the last daily snapshot: up to 24 hours of records are "
                                       "unrecoverable after a bad migration or a destructive query."))
    if n_backups == 0 and not walg and not pitr:
        out.append(make_finding("supabase_backups_pitr", "availability", "high", "No database backups on file",
                                extra="backups", evidence_kinds=("availability",),
                                metrics={"backups": 0, "walg_enabled": False, "region": _s(_v(cfg, "region"))},
                                detail="The Management API lists no backups and WAL archiving is off: a destructive "
                                       "change cannot be undone at all."))
    elif n_backups:
        out.append(make_finding("supabase_backups_pitr", "availability", "info", f"{n_backups} database backups on file",
                                direction="supports", extra="backups", evidence_kinds=("availability",),
                                metrics={"backups": n_backups}))
    return out


def _p_network_ssl(rows, source, facts=None):
    out = []
    net = _cfg(rows, "/network-restrictions")
    if isinstance(net, dict):
        config = net.get("config") if isinstance(net.get("config"), dict) else {}
        cidrs = _list(config.get("dbAllowedCidrs")) + _list(config.get("dbAllowedCidrsV6"))
        entitlement = _s(_v(net, "entitlement"))
        wide_open = not cidrs or any(c.strip() in ("0.0.0.0/0", "::/0") for c in cidrs)
        metrics = {"cidrs": cidrs, "entitlement": entitlement, "status": _s(_v(net, "status"))}
        if wide_open:
            out.append(make_finding("supabase_network_and_ssl", "security", "medium",
                                    "Database accepts connections from any IP address", extra="network",
                                    evidence_kinds=("access_control",), metrics=metrics,
                                    detail=("Network restrictions are not available on this plan." if entitlement == "disallowed"
                                            else "No CIDR allow-list is applied (or it contains 0.0.0.0/0); the only "
                                                 "barrier to the database port is the password.")))
        else:
            out.append(make_finding("supabase_network_and_ssl", "security", "info",
                                    f"Database network access restricted to {len(cidrs)} CIDR ranges",
                                    direction="supports", extra="network", evidence_kinds=("access_control",),
                                    metrics=metrics))
    ssl = _cfg(rows, "/ssl-enforcement")
    if isinstance(ssl, dict):
        current = ssl.get("currentConfig") if isinstance(ssl.get("currentConfig"), dict) else {}
        enforced = _bool(current.get("database"))
        metrics = {"database": enforced, "applied": _bool(_v(ssl, "appliedSuccessfully", default=True))}
        if enforced:
            out.append(make_finding("supabase_network_and_ssl", "security", "info",
                                    "SSL is enforced on database connections", direction="supports", extra="ssl",
                                    evidence_kinds=("access_control",), metrics=metrics))
        else:
            out.append(make_finding("supabase_network_and_ssl", "security", "medium",
                                    "SSL is not enforced on database connections", extra="ssl",
                                    evidence_kinds=("access_control",), metrics=metrics,
                                    detail="Clients may connect in clear text; credentials and rows can be read on the path."))
    return out


def _p_edge_functions(rows, source, facts=None):
    fns = _cfg(rows, "/functions")
    if isinstance(fns, dict) and isinstance(fns.get("functions"), list):
        fns = fns["functions"]
    if not isinstance(fns, list):
        return []
    facts = facts if facts is not None else {}
    out = []
    seen = 0
    for fn in fns:
        if not isinstance(fn, dict):
            continue
        seen += 1
        slug = _s(_v(fn, "slug")) or _s(_v(fn, "name")) or _s(_v(fn, "id"))
        verify = _v(fn, "verify_jwt")
        if verify is None or _bool(verify):
            continue
        webhook = bool(WEBHOOK_FUNC_RE.search(slug))
        out.append(make_finding("supabase_edge_functions_verify_jwt", "security", "low" if webhook else "medium",
                                f"Edge function {slug} does not verify JWTs", object_schema="supabase_functions",
                                object_name=slug, extra=slug, evidence_kinds=("access_control",),
                                metrics={"slug": slug, "verify_jwt": False, "status": _s(_v(fn, "status")),
                                         "version": _s(_v(fn, "version")), "webhook_name": webhook},
                                detail=("Name suggests a webhook target; confirm the handler validates the sender's "
                                        "signature itself." if webhook else
                                        "Anyone on the internet can invoke it without a Supabase session; whatever it "
                                        "does with the service key is public.")))
    facts["edge_functions"] = seen
    if seen and not out:
        out.append(make_finding("supabase_edge_functions_verify_jwt", "security", "info",
                                f"All {seen} edge functions verify JWTs", direction="supports", extra="all_verify",
                                object_schema="supabase_functions", evidence_kinds=("access_control",),
                                metrics={"functions": seen}))
    return out


# ── SQL (one SELECT/WITH each, catalog-only, bounded) ─────────────────────────────────

_PG_PII = f"'({PII_COLUMN_PATTERN})'"

_SQL = {
    "rls_disabled_tables": {
        "postgres": "select schemaname, tablename, rowsecurity from pg_catalog.pg_tables "
                    "where schemaname = 'public' order by tablename limit 500"},
    "rls_enabled_no_policy": {
        "postgres": "select t.schemaname, t.tablename from pg_catalog.pg_tables t where t.schemaname = 'public' "
                    "and t.rowsecurity and not exists (select 1 from pg_catalog.pg_policies p "
                    "where p.schemaname = t.schemaname and p.tablename = t.tablename) order by t.tablename limit 500"},
    "anon_or_public_grants": {
        "postgres": "select g.grantee, g.table_schema as schemaname, g.table_name as tablename, g.privilege_type, "
                    "t.rowsecurity from information_schema.role_table_grants g "
                    "join pg_catalog.pg_tables t on t.schemaname = g.table_schema and t.tablename = g.table_name "
                    "where g.table_schema = 'public' and g.grantee in ('anon', 'PUBLIC') "
                    "order by g.table_name, g.grantee, g.privilege_type limit 500"},
    "tables_without_primary_key": {
        "postgres": "select n.nspname as schemaname, c.relname as tablename, c.reltuples::bigint as est_rows "
                    "from pg_catalog.pg_class c join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
                    f"where c.relkind in ('r', 'p') and {_user_schema('n.nspname')} "
                    "and not exists (select 1 from pg_catalog.pg_constraint k where k.conrelid = c.oid and k.contype = 'p') "
                    "order by c.reltuples desc limit 200",
        "mysql": "select t.table_schema as schemaname, t.table_name as tablename, t.table_rows as est_rows "
                 "from information_schema.tables t where t.table_schema = database() and t.table_type = 'BASE TABLE' "
                 "and not exists (select 1 from information_schema.table_constraints k where k.table_schema = t.table_schema "
                 "and k.table_name = t.table_name and k.constraint_type = 'PRIMARY KEY') order by t.table_rows desc limit 200"},
    "unindexed_foreign_keys": {
        "postgres": "select n.nspname as schemaname, c.relname as tablename, k.conname, rc.relname as referenced_table, "
                    "rc.reltuples::bigint as referenced_rows, c.reltuples::bigint as est_rows, "
                    "(select array_agg(a.attname order by x.ord) from unnest(k.conkey) with ordinality as x(attnum, ord) "
                    "join pg_catalog.pg_attribute a on a.attrelid = k.conrelid and a.attnum = x.attnum) as fk_columns "
                    "from pg_catalog.pg_constraint k join pg_catalog.pg_class c on c.oid = k.conrelid "
                    "join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
                    "join pg_catalog.pg_class rc on rc.oid = k.confrelid "
                    f"where k.contype = 'f' and {_user_schema('n.nspname')} "
                    "and not exists (select 1 from pg_catalog.pg_index i where i.indrelid = k.conrelid "
                    "and (i.indkey::int2[])[0:cardinality(k.conkey) - 1] @> k.conkey) "
                    "order by rc.reltuples desc, c.relname limit 200"},
    "unused_indexes": {
        "postgres": "select s.schemaname, s.relname as tablename, s.indexrelname as indexname, s.idx_scan, "
                    "pg_catalog.pg_relation_size(s.indexrelid) as index_bytes "
                    "from pg_catalog.pg_stat_user_indexes s join pg_catalog.pg_index i on i.indexrelid = s.indexrelid "
                    "where s.idx_scan = 0 and not i.indisunique and not i.indisprimary "
                    f"and pg_catalog.pg_relation_size(s.indexrelid) > 8388608 and {_user_schema('s.schemaname')} "
                    "order by pg_catalog.pg_relation_size(s.indexrelid) desc limit 100",
        "mysql": "select object_schema as schemaname, object_name as tablename, index_name as indexname, 0 as idx_scan, "
                 "0 as index_bytes from sys.schema_unused_indexes where object_schema = database() "
                 "order by object_name, index_name limit 100"},
    "duplicate_indexes": {
        "postgres": "select n.nspname as schemaname, c.relname as tablename, "
                    "array_agg(ic.relname order by ic.relname) as indexes, count(*) as n "
                    "from pg_catalog.pg_index i join pg_catalog.pg_class c on c.oid = i.indrelid "
                    "join pg_catalog.pg_class ic on ic.oid = i.indexrelid "
                    "join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
                    f"where {_user_schema('n.nspname')} "
                    "group by n.nspname, c.relname, i.indrelid, i.indkey, i.indclass, coalesce(i.indexprs::text, ''), "
                    "coalesce(i.indpred::text, '') having count(*) > 1 order by n.nspname, c.relname limit 100"},
    "dead_tuple_bloat": {
        "postgres": "select schemaname, relname as tablename, n_live_tup, n_dead_tup, last_autovacuum "
                    "from pg_catalog.pg_stat_user_tables where n_dead_tup > 50000 "
                    f"and n_dead_tup > 0.2 * greatest(n_live_tup, 1) and {_user_schema('schemaname')} "
                    "order by n_dead_tup desc limit 100"},
    "vacuum_stale": {
        "postgres": "select schemaname, relname as tablename, n_live_tup, last_autovacuum, last_autoanalyze "
                    "from pg_catalog.pg_stat_user_tables where n_live_tup > 100000 "
                    "and (last_autovacuum is null or last_autovacuum < now() - interval '7 days') "
                    f"and {_user_schema('schemaname')} order by n_live_tup desc limit 100"},
    "sequence_headroom": {
        "postgres": "select schemaname, sequencename, last_value, max_value, "
                    "last_value::numeric / nullif(max_value, 0)::numeric as used_ratio "
                    "from pg_catalog.pg_sequences where last_value is not null and max_value > 0 "
                    "and last_value::numeric / max_value::numeric > 0.6 order by used_ratio desc limit 100"},
    "slow_query_classes": {
        "postgres": "select s.queryid, s.calls, s.total_exec_time, s.mean_exec_time, s.rows, left(s.query, 200) as query "
                    "from pg_stat_statements s where (s.mean_exec_time > 250 or s.calls > 100000) "
                    "and s.query not like '%pg_stat_statements%' order by s.total_exec_time desc limit 15"},
    "missing_audit_columns": {
        "postgres": "select t.schemaname, t.tablename, bool_or(c.column_name in ('created_at', 'inserted_at')) as has_created, "
                    "bool_or(c.column_name = 'updated_at') as has_updated, "
                    "exists (select 1 from information_schema.role_table_grants g where g.table_schema = t.schemaname "
                    "and g.table_name = t.tablename and g.privilege_type = 'UPDATE' and g.grantee <> t.tableowner) as has_update_grants "
                    "from pg_catalog.pg_tables t join information_schema.columns c "
                    "on c.table_schema = t.schemaname and c.table_name = t.tablename "
                    "where t.schemaname = 'public' group by t.schemaname, t.tablename, t.tableowner order by t.tablename limit 500",
        "mysql": "select t.table_schema as schemaname, t.table_name as tablename, "
                 "max(c.column_name in ('created_at', 'inserted_at')) as has_created, "
                 "max(c.column_name = 'updated_at') as has_updated, 1 as has_update_grants "
                 "from information_schema.tables t join information_schema.columns c "
                 "on c.table_schema = t.table_schema and c.table_name = t.table_name "
                 "where t.table_schema = database() and t.table_type = 'BASE TABLE' "
                 "group by t.table_schema, t.table_name order by t.table_name limit 500"},
    "audit_trail_presence": {
        "postgres": "select schemaname, tablename from pg_catalog.pg_tables where schemaname = 'public' "
                    f"and tablename ~ '{AUDIT_TABLE_PATTERN}' order by tablename limit 100",
        "mysql": "select table_schema as schemaname, table_name as tablename from information_schema.tables "
                 f"where table_schema = database() and table_type = 'BASE TABLE' and table_name regexp '{AUDIT_TABLE_PATTERN}' "
                 "order by table_name limit 100"},
    "pii_columns_inventory": {
        "postgres": "select c.table_schema as schemaname, c.table_name as tablename, "
                    "array_agg(c.column_name order by c.column_name) as columns from information_schema.columns c "
                    "join pg_catalog.pg_tables t on t.schemaname = c.table_schema and t.tablename = c.table_name "
                    f"where c.table_schema = 'public' and c.column_name ~* {_PG_PII} "
                    "group by c.table_schema, c.table_name order by c.table_name limit 500",
        "mysql": "select c.table_schema as schemaname, c.table_name as tablename, "
                 "group_concat(c.column_name order by c.column_name) as columns from information_schema.columns c "
                 f"where c.table_schema = database() and lower(c.column_name) regexp {_PG_PII} "
                 "group by c.table_schema, c.table_name order by c.table_name limit 500",
        "bigquery": "select table_schema as schemaname, table_name as tablename, "
                    "array_agg(column_name order by column_name) as columns "
                    "from `{project}.{dataset}`.INFORMATION_SCHEMA.COLUMNS "
                    f"where regexp_contains(lower(column_name), r{_PG_PII}) "
                    "group by table_schema, table_name order by table_name limit 500",
        "snowflake": "select table_schema as schemaname, table_name as tablename, "
                     "listagg(column_name, ',') within group (order by column_name) as columns "
                     "from information_schema.columns where table_schema <> 'INFORMATION_SCHEMA' "
                     f"and regexp_like(lower(column_name), '.*({PII_COLUMN_PATTERN}).*') "
                     "group by table_schema, table_name order by table_name limit 500"},
    "pii_exposed_tables": {
        "postgres": "select c.table_schema as schemaname, c.table_name as tablename, t.rowsecurity, "
                    "array_agg(c.column_name order by c.column_name) as columns from information_schema.columns c "
                    "join pg_catalog.pg_tables t on t.schemaname = c.table_schema and t.tablename = c.table_name "
                    f"where c.table_schema = 'public' and not t.rowsecurity and c.column_name ~* {_PG_PII} "
                    "group by c.table_schema, c.table_name, t.rowsecurity order by c.table_name limit 200"},
    "soft_delete_without_purge": {
        "postgres": "select c.table_schema as schemaname, c.table_name as tablename from information_schema.columns c "
                    "join pg_catalog.pg_tables t on t.schemaname = c.table_schema and t.tablename = c.table_name "
                    "where c.table_schema = 'public' and c.column_name = 'deleted_at' order by c.table_name limit 200",
        "mysql": "select c.table_schema as schemaname, c.table_name as tablename from information_schema.columns c "
                 "where c.table_schema = database() and c.column_name = 'deleted_at' order by c.table_name limit 200"},
    "pg_cron_jobs": {
        "postgres": "select jobid, jobname, schedule, active from cron.job order by jobid limit 100"},
    "security_definer_functions": {
        "postgres": "select n.nspname as schemaname, p.proname as funcname, p.oid::regprocedure::text as signature "
                    "from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid = p.pronamespace "
                    f"where p.prosecdef and {_user_schema('n.nspname')} order by n.nspname, p.proname limit 200"},
    "extensions_in_public": {
        "postgres": "select e.extname, e.extversion, n.nspname as schemaname from pg_catalog.pg_extension e "
                    "join pg_catalog.pg_namespace n on n.oid = e.extnamespace order by e.extname limit 200"},
    "schema_migrations_state": {
        "postgres": "select count(*) as n from information_schema.tables "
                    "where table_schema = 'supabase_migrations' and table_name = 'schema_migrations'"},
    "schema_migrations_latest": {
        "postgres": "select count(*) as n, max(version) as latest from supabase_migrations.schema_migrations"},
    "ai_call_logging_presence": {
        "postgres": "select schemaname, tablename from pg_catalog.pg_tables where schemaname = 'public' "
                    f"and tablename ~* '({AI_TABLE_PATTERN})' order by tablename limit 100",
        "mysql": "select table_schema as schemaname, table_name as tablename from information_schema.tables "
                 f"where table_schema = database() and table_type = 'BASE TABLE' and lower(table_name) regexp '({AI_TABLE_PATTERN})' "
                 "order by table_name limit 100"},
    "unvalidated_constraints": {
        "postgres": "select n.nspname as schemaname, c.relname as tablename, k.conname, k.contype "
                    "from pg_catalog.pg_constraint k join pg_catalog.pg_class c on c.oid = k.conrelid "
                    "join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
                    f"where not k.convalidated and {_user_schema('n.nspname')} order by n.nspname, c.relname, k.conname limit 5"},
    "table_inventory_facts": {
        "postgres": "select (select count(*) from pg_catalog.pg_tables where schemaname = 'public') as tables, "
                    "(select count(*) from pg_catalog.pg_views where schemaname = 'public') as views, "
                    "(select count(*) from pg_catalog.pg_matviews where schemaname = 'public') as matviews, "
                    "(select count(*) from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid = p.pronamespace "
                    "where n.nspname = 'public') as functions, "
                    "pg_catalog.pg_database_size(current_database()) as db_size_bytes, "
                    "pg_catalog.pg_size_pretty(pg_catalog.pg_database_size(current_database())) as db_size, "
                    "current_database() as dbname",
        "mysql": "select (select count(*) from information_schema.tables where table_schema = database() "
                 "and table_type = 'BASE TABLE') as tables, "
                 "(select count(*) from information_schema.tables where table_schema = database() and table_type = 'VIEW') as views, "
                 "0 as matviews, (select count(*) from information_schema.routines where routine_schema = database()) as functions, "
                 "(select coalesce(sum(data_length + index_length), 0) from information_schema.tables "
                 "where table_schema = database()) as db_size_bytes, database() as dbname",
        "bigquery": "select (select count(*) from `{project}.{dataset}`.INFORMATION_SCHEMA.TABLES where table_type = 'BASE TABLE') as tables, "
                    "(select count(*) from `{project}.{dataset}`.INFORMATION_SCHEMA.TABLES where table_type = 'VIEW') as views, "
                    "(select count(*) from `{project}.{dataset}`.INFORMATION_SCHEMA.TABLES where table_type = 'MATERIALIZED VIEW') as matviews, "
                    "(select count(*) from `{project}.{dataset}`.INFORMATION_SCHEMA.ROUTINES) as functions, "
                    "(select coalesce(sum(size_bytes), 0) from `{project}.{dataset}.__TABLES__`) as db_size_bytes, "
                    "'{dataset}' as dbname",
        "snowflake": "select (select count(*) from information_schema.tables where table_schema <> 'INFORMATION_SCHEMA' "
                     "and table_type = 'BASE TABLE') as tables, "
                     "(select count(*) from information_schema.views where table_schema <> 'INFORMATION_SCHEMA') as views, "
                     "0 as matviews, "
                     "(select count(*) from information_schema.functions where function_schema <> 'INFORMATION_SCHEMA') as functions, "
                     "(select coalesce(sum(bytes), 0) from information_schema.tables where table_schema <> 'INFORMATION_SCHEMA') as db_size_bytes, "
                     "current_database() as dbname"},
    "long_running_transactions": {
        "postgres": "select pid, usename, state, application_name, extract(epoch from now() - xact_start) as xact_age_s, "
                    "split_part(ltrim(query), ' ', 1) as verb from pg_catalog.pg_stat_activity "
                    "where state <> 'idle' and xact_start is not null and xact_start < now() - interval '5 minutes' "
                    "and pid <> pg_backend_pid() and backend_type = 'client backend' order by xact_start limit 50",
        "mysql": "select id as pid, user as usename, command as state, time as xact_age_s, '' as application_name, "
                 "'' as verb from information_schema.processlist where command <> 'Sleep' and time > 300 "
                 "and id <> connection_id() order by time desc limit 50"},
    "timestamp_without_timezone": {
        "postgres": "select c.table_schema as schemaname, c.table_name as tablename, "
                    "array_agg(c.column_name order by c.column_name) as columns from information_schema.columns c "
                    "join pg_catalog.pg_tables t on t.schemaname = c.table_schema and t.tablename = c.table_name "
                    "where c.table_schema = 'public' and c.data_type = 'timestamp without time zone' "
                    "group by c.table_schema, c.table_name order by c.table_name limit 200"},
    "uuid_text_keys": {
        "postgres": "select n.nspname as schemaname, c.relname as tablename, a.attname as column_name "
                    "from pg_catalog.pg_constraint k join pg_catalog.pg_class c on c.oid = k.conrelid "
                    "join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
                    "join pg_catalog.pg_attribute a on a.attrelid = k.conrelid and a.attnum = any(k.conkey) "
                    "join pg_catalog.pg_type ty on ty.oid = a.atttypid "
                    "where k.contype = 'p' and ty.typname in ('text', 'varchar', 'bpchar') "
                    f"and (a.attname = 'id' or a.attname like '%\\_id') and {_user_schema('n.nspname')} "
                    "order by n.nspname, c.relname limit 200"},
    "partition_or_cluster_missing": {
        "bigquery": "select t.table_schema as schemaname, t.table_name as tablename, s.size_bytes, s.row_count "
                    "from `{project}.{dataset}`.INFORMATION_SCHEMA.TABLES t "
                    "join `{project}.{dataset}.__TABLES__` s on s.table_id = t.table_name "
                    "where t.table_type = 'BASE TABLE' and s.size_bytes > 10737418240 "
                    "and not exists (select 1 from `{project}.{dataset}`.INFORMATION_SCHEMA.COLUMNS c "
                    "where c.table_name = t.table_name and (c.is_partitioning_column = 'YES' "
                    "or c.clustering_ordinal_position is not null)) order by s.size_bytes desc limit 50"},
    "privileged_login_roles": {
        "postgres": "select r.rolname, r.rolsuper, r.rolbypassrls, r.rolcreaterole, r.rolcreatedb, r.rolreplication, "
                    "r.rolvaliduntil from pg_catalog.pg_roles r where r.rolcanlogin and (r.rolsuper or r.rolbypassrls) "
                    f"and r.rolname not in {_PLATFORM_ROLES_SQL} and r.rolname not like 'pg\\_%' "
                    "order by r.rolname limit 100"},
    "invalid_indexes": {
        "postgres": "select n.nspname as schemaname, c.relname as tablename, ic.relname as indexname, i.indisunique, "
                    "pg_catalog.pg_relation_size(i.indexrelid) as index_bytes "
                    "from pg_catalog.pg_index i join pg_catalog.pg_class ic on ic.oid = i.indexrelid "
                    "join pg_catalog.pg_class c on c.oid = i.indrelid "
                    "join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
                    f"where not i.indisvalid and {_user_schema('n.nspname')} "
                    "order by n.nspname, c.relname, ic.relname limit 100"},
    "cascade_delete_blast_radius": {
        "postgres": "select n.nspname as schemaname, c.relname as tablename, k.conname, rn.nspname as referenced_schema, "
                    "rc.relname as referenced_table, c.reltuples::bigint as est_rows, rc.reltuples::bigint as referenced_rows "
                    "from pg_catalog.pg_constraint k join pg_catalog.pg_class c on c.oid = k.conrelid "
                    "join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
                    "join pg_catalog.pg_class rc on rc.oid = k.confrelid "
                    "join pg_catalog.pg_namespace rn on rn.oid = rc.relnamespace "
                    f"where k.contype = 'f' and k.confdeltype = 'c' and c.reltuples > 100000 and {_user_schema('n.nspname')} "
                    "order by c.reltuples desc, k.conname limit 100"},
    "disabled_triggers": {
        "postgres": "select n.nspname as schemaname, c.relname as tablename, t.tgname as triggername, t.tgisinternal, "
                    "t.tgenabled::text as tgenabled from pg_catalog.pg_trigger t "
                    "join pg_catalog.pg_class c on c.oid = t.tgrelid "
                    "join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
                    f"where t.tgenabled = 'D' and {_user_schema('n.nspname')} "
                    "order by n.nspname, c.relname, t.tgname limit 100"},
    "large_tables_without_index": {
        "postgres": "select n.nspname as schemaname, c.relname as tablename, c.reltuples::bigint as est_rows, "
                    "pg_catalog.pg_total_relation_size(c.oid) as total_bytes "
                    "from pg_catalog.pg_class c join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
                    f"where c.relkind in ('r', 'p') and c.reltuples > 1000000 and {_user_schema('n.nspname')} "
                    "and not exists (select 1 from pg_catalog.pg_index i where i.indrelid = c.oid) "
                    "order by c.reltuples desc limit 50",
        "mysql": "select t.table_schema as schemaname, t.table_name as tablename, t.table_rows as est_rows, "
                 "t.data_length + t.index_length as total_bytes from information_schema.tables t "
                 "where t.table_schema = database() and t.table_type = 'BASE TABLE' and t.table_rows > 1000000 "
                 "and not exists (select 1 from information_schema.statistics s where s.table_schema = t.table_schema "
                 "and s.table_name = t.table_name) order by t.table_rows desc limit 50"},
    "views_exposed_over_rls_tables": {
        "postgres": "select vn.nspname as schemaname, v.relname as viewname, v.relkind::text as relkind, "
                    "coalesce(v.reloptions::text, '') as reloptions, array_agg(distinct g.grantee::text) as grantees, "
                    "array_agg(distinct tn.nspname || '.' || t.relname) as base_tables "
                    "from pg_catalog.pg_class v join pg_catalog.pg_namespace vn on vn.oid = v.relnamespace "
                    "join pg_catalog.pg_rewrite rw on rw.ev_class = v.oid "
                    "join pg_catalog.pg_depend d on d.classid = 'pg_catalog.pg_rewrite'::regclass and d.objid = rw.oid "
                    "and d.refclassid = 'pg_catalog.pg_class'::regclass "
                    "join pg_catalog.pg_class t on t.oid = d.refobjid and t.oid <> v.oid and t.relkind in ('r', 'p') "
                    "join pg_catalog.pg_namespace tn on tn.oid = t.relnamespace "
                    "join information_schema.role_table_grants g on g.table_schema = vn.nspname "
                    "and g.table_name = v.relname and g.privilege_type = 'SELECT' "
                    "and g.grantee in ('anon', 'authenticated', 'PUBLIC') "
                    f"where v.relkind in ('v', 'm') and t.relrowsecurity and {_user_schema('vn.nspname')} "
                    "group by vn.nspname, v.relname, v.relkind, v.reloptions order by vn.nspname, v.relname limit 200"},
    "pii_readable_by_anon": {
        "postgres": "select c.table_schema as schemaname, c.table_name as tablename, t.rowsecurity, "
                    "array_agg(c.column_name order by c.column_name) as columns, "
                    "(select array_agg(distinct g.grantee::text) from information_schema.role_table_grants g "
                    "where g.table_schema = c.table_schema and g.table_name = c.table_name "
                    "and g.privilege_type = 'SELECT' and g.grantee in ('anon', 'PUBLIC')) as grantees "
                    "from information_schema.columns c "
                    "join pg_catalog.pg_tables t on t.schemaname = c.table_schema and t.tablename = c.table_name "
                    f"where c.table_schema = 'public' and c.column_name ~* {_PG_PII} "
                    "and c.data_type in ('text', 'character varying', 'character', 'json', 'jsonb') "
                    "and exists (select 1 from information_schema.role_table_grants g where g.table_schema = c.table_schema "
                    "and g.table_name = c.table_name and g.privilege_type = 'SELECT' and g.grantee in ('anon', 'PUBLIC')) "
                    "group by c.table_schema, c.table_name, t.rowsecurity order by c.table_name limit 200"},
    "updated_at_without_trigger": {
        "postgres": "select t.schemaname, t.tablename from pg_catalog.pg_tables t "
                    "join information_schema.columns c on c.table_schema = t.schemaname and c.table_name = t.tablename "
                    "where t.schemaname = 'public' and c.column_name = 'updated_at' "
                    "and not exists (select 1 from pg_catalog.pg_trigger tg "
                    "join pg_catalog.pg_class tc on tc.oid = tg.tgrelid "
                    "join pg_catalog.pg_namespace tn on tn.oid = tc.relnamespace "
                    "where tn.nspname = t.schemaname and tc.relname = t.tablename and not tg.tgisinternal "
                    "and (tg.tgtype::int & 16) <> 0) order by t.tablename limit 500",
        "mysql": "select c.table_schema as schemaname, c.table_name as tablename from information_schema.columns c "
                 "where c.table_schema = database() and c.column_name = 'updated_at' "
                 "and lower(c.extra) not like '%on update%' "
                 "and not exists (select 1 from information_schema.triggers tr where tr.event_object_schema = c.table_schema "
                 "and tr.event_object_table = c.table_name and tr.event_manipulation = 'UPDATE') "
                 "order by c.table_name limit 500"},
    "idle_in_transaction_sessions": {
        "postgres": "select pid, usename, application_name, state, extract(epoch from now() - state_change) as idle_s, "
                    "extract(epoch from now() - xact_start) as xact_age_s from pg_catalog.pg_stat_activity "
                    "where state in ('idle in transaction', 'idle in transaction (aborted)') "
                    "and state_change < now() - interval '5 minutes' and pid <> pg_backend_pid() "
                    "and backend_type = 'client backend' order by state_change limit 50",
        "mysql": "select p.id as pid, p.user as usename, '' as application_name, t.trx_state as state, p.time as idle_s, "
                 "timestampdiff(second, t.trx_started, now()) as xact_age_s from information_schema.innodb_trx t "
                 "join information_schema.processlist p on p.id = t.trx_mysql_thread_id "
                 "where p.command = 'Sleep' and p.time > 300 order by p.time desc limit 50"},
    "connection_saturation": {
        "postgres": "select count(*) as connections, count(*) filter (where state = 'active') as active, "
                    "count(*) filter (where backend_type = 'client backend') as client_connections, "
                    "current_setting('max_connections')::int as max_connections from pg_catalog.pg_stat_activity",
        "mysql": "select (select count(*) from information_schema.processlist) as connections, "
                 "(select count(*) from information_schema.processlist where command <> 'Sleep') as active, "
                 "(select count(*) from information_schema.processlist) as client_connections, "
                 "@@max_connections as max_connections"},
    "replication_slots_lagging": {
        "postgres": "select s.slot_name, s.slot_type, s.active, s.database, s.active_pid, "
                    "pg_catalog.pg_wal_lsn_diff(case when pg_catalog.pg_is_in_recovery() "
                    "then pg_catalog.pg_last_wal_replay_lsn() else pg_catalog.pg_current_wal_lsn() end, "
                    "s.restart_lsn) as retained_bytes from pg_catalog.pg_replication_slots s "
                    "order by retained_bytes desc nulls last, s.slot_name limit 50"},
    "public_storage_buckets": {
        "postgres": "select id, name, public, file_size_limit, created_at from storage.buckets order by name limit 200"},
    # Facts-only probes: they emit NO findings, they feed snapshot facts that chains and
    # policy synthesis read (blast radius, candidate RLS owner columns).
    "fk_graph_edges": {
        "postgres": "select n.nspname as child_schema, c.relname as child_table, rn.nspname as parent_schema, "
                    "rc.relname as parent_table, "
                    "(select array_agg(a.attname order by x.ord) from unnest(k.conkey) with ordinality as x(attnum, ord) "
                    "join pg_catalog.pg_attribute a on a.attrelid = k.conrelid and a.attnum = x.attnum) as fk_columns "
                    "from pg_catalog.pg_constraint k join pg_catalog.pg_class c on c.oid = k.conrelid "
                    "join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
                    "join pg_catalog.pg_class rc on rc.oid = k.confrelid "
                    "join pg_catalog.pg_namespace rn on rn.oid = rc.relnamespace "
                    f"where k.contype = 'f' and {_user_schema('n.nspname')} order by c.relname limit 1000"},
    "column_inventory": {
        "postgres": "select table_name as tablename, array_agg(column_name order by ordinal_position) as columns "
                    "from information_schema.columns where table_schema = 'public' "
                    "group by table_name order by table_name limit 500"},
}


def _probe(pid, title, category, tier, evidence_kinds, parse, remediation, **gates):
    sql = _SQL.get(pid, {})
    return {"id": pid, "title": title, "category": category, "tier": tier,
            "dialects": gates.pop("dialects", None) or sorted(sql.keys()),
            "evidence_kinds": list(evidence_kinds), "sql": sql, "parse": parse,
            "remediation": remediation, **gates}


PROBES = [
    _probe("table_inventory_facts", "Table/view/function counts and database size", "availability", "cheap",
           ("availability",), _p_inventory, "Informational; feeds the posture snapshot. No action."),
    _probe("fk_graph_edges", "Foreign-key graph edges (facts for blast-radius chains)", "integrity", "cheap",
           ("integrity",), _p_fk_graph, "Facts-only; no findings by design."),
    _probe("column_inventory", "Column names per table (facts for policy synthesis)", "privacy", "cheap",
           ("data_minimization",), _p_columns, "Facts-only; no findings by design."),
    _probe("extensions_in_public", "Extensions installed in schema public", "schema_drift", "cheap",
           ("change_control",), _p_extensions,
           "Move extensions to the `extensions` schema in a new migration (`create extension … with schema extensions` "
           "after dropping from public in a maintenance window); never leave extension objects in the app schema."),
    _probe("schema_migrations_state", "Migration history table present", "schema_drift", "cheap",
           ("change_control",), _p_migrations_state,
           "Adopt `supabase db push` / versioned migrations under supabase/migrations so every schema change is attributable."),
    _probe("schema_migrations_latest", "Migrations applied and latest version", "schema_drift", "cheap",
           ("change_control",), _p_migrations_latest,
           "Informational; the steering loop compares this with the repo's migration files.",
           requires_fact="has_schema_migrations"),
    _probe("rls_disabled_tables", "Public tables without row-level security", "security", "cheap",
           ("access_control",), _p_rls_disabled,
           "Add `alter table public.<table> enable row level security` plus owner-scoped policies "
           "(`using (auth.uid() = owner_id)`) in a new migration. Do not enable RLS without policies — it breaks the client."),
    _probe("rls_enabled_no_policy", "RLS enabled with zero policies", "security", "cheap",
           ("access_control",), _p_rls_no_policy,
           "Write explicit policies per role in a migration (select/insert/update/delete, owner- or tenant-scoped) "
           "or confirm the table is service-role-only and document that."),
    _probe("anon_or_public_grants", "anon / PUBLIC table grants", "security", "cheap",
           ("access_control", "data_minimization"), _p_anon_grants,
           "In a migration: `revoke insert, update, delete on public.<table> from anon` (and `select` unless the table "
           "is intentionally public reference data); keep grants to `authenticated` gated by RLS policies."),
    _probe("pii_columns_inventory", "Columns that look like personal data", "privacy", "cheap",
           ("data_minimization",), _p_pii_inventory,
           "Inventory entry: confirm each column is needed, encrypted where appropriate, and covered by RLS and retention."),
    _probe("pii_exposed_tables", "Personal-data tables with RLS off", "privacy", "cheap",
           ("data_minimization", "access_control"), _p_pii_exposed,
           "Enable RLS with owner-scoped policies on this table in a new migration before anything else; "
           "if the columns are not needed, drop them in the same change."),
    _probe("tables_without_primary_key", "Tables without a primary key", "integrity", "cheap",
           ("integrity",), _p_no_pk,
           "Add `alter table <t> add primary key (id)` (or a `bigint generated always as identity` column first) in a migration."),
    _probe("unindexed_foreign_keys", "Foreign keys without a covering index", "performance", "cheap",
           ("availability", "integrity"), _p_unindexed_fk,
           "Add `create index concurrently <t>_<col>_idx on <t> (<col>)` in a migration (run outside a transaction)."),
    _probe("sequence_headroom", "Sequences approaching max_value", "availability", "cheap",
           ("availability",), _p_sequence_headroom,
           "Migrate the column to bigint (`alter table <t> alter column id type bigint`) and `alter sequence … as bigint` "
           "before it wraps; plan a maintenance window for large tables."),
    _probe("missing_audit_columns", "Tables without created_at / updated_at", "audit", "cheap",
           ("audit_trail",), _p_missing_audit,
           "Add `created_at timestamptz not null default now()` and `updated_at timestamptz` with a `moddatetime` "
           "trigger in a migration; backfill created_at from the best available source."),
    _probe("audit_trail_presence", "Audit / event tables present", "audit", "cheap",
           ("audit_trail",), _p_audit_trail,
           "Add an append-only `<domain>_events` table (actor, action, subject, at, payload) written by every material "
           "workflow; revoke update/delete on it from all app roles."),
    _probe("ai_call_logging_presence", "Model-call / token-usage log tables present", "ai_governance", "cheap",
           ("ai_logging", "audit_trail"), _p_ai_logging,
           "If the project calls models, add a `model_calls` (or `token_usage`) table recording provider, model, route, "
           "tokens, cost, latency, caller and subject id for every call."),
    _probe("unvalidated_constraints", "Constraints marked NOT VALID", "integrity", "cheap",
           ("integrity",), _p_unvalidated,
           "Run `alter table <t> validate constraint <c>` in a migration after fixing any violating rows "
           "(find them with an anti-join in a one-off read)."),
    _probe("long_running_transactions", "Transactions open longer than 5 minutes", "availability", "cheap",
           ("availability",), _p_long_txns,
           "Find the caller by application_name/pid; add `idle_in_transaction_session_timeout` and `statement_timeout` "
           "on the app role; fix the code path that holds a transaction across I/O."),
    _probe("unused_indexes", "Indexes never scanned (> 8 MB)", "cost", "medium",
           ("availability",), _p_unused_indexes,
           "Confirm with a second reading after a full traffic cycle, then `drop index concurrently <idx>` in a migration."),
    _probe("duplicate_indexes", "Indexes with identical definitions", "cost", "medium",
           ("availability",), _p_duplicate_indexes,
           "Keep one (prefer the unique/primary one), `drop index concurrently` the rest in a migration."),
    _probe("dead_tuple_bloat", "Tables with heavy dead-tuple bloat", "availability", "medium",
           ("availability",), _p_dead_tuples,
           "Lower `autovacuum_vacuum_scale_factor` for the table (`alter table <t> set (autovacuum_vacuum_scale_factor = 0.02)`) "
           "and check for long transactions or replication slots holding back cleanup."),
    _probe("vacuum_stale", "Large tables not autovacuumed in 7 days", "availability", "medium",
           ("availability",), _p_vacuum_stale,
           "Verify autovacuum is enabled for the table and not starved (autovacuum_max_workers, cost limits); "
           "look for a long-open transaction pinning the xmin horizon."),
    _probe("slow_query_classes", "Dominant / slow query classes (pg_stat_statements)", "performance", "medium",
           ("availability",), _p_slow_queries,
           "Explain the query class, add the missing index or rewrite the hot path in the repo; reset stats after the fix "
           "to confirm.", requires_capability="pg_stat_statements"),
    _probe("security_definer_functions", "Definer-rights functions in app schemas", "security", "medium",
           ("access_control",), _p_secdef_functions,
           "Set `security invoker` unless owner rights are required; if required, `set search_path = ''` on the function, "
           "revoke execute from public/anon and re-check auth.uid() inside."),
    _probe("soft_delete_without_purge", "Soft-delete columns without a visible purge", "retention", "heavy",
           ("retention",), _p_soft_delete,
           "Add a scheduled purge (pg_cron or an app job) that hard-deletes rows past the retention window and document "
           "the window per table."),
    _probe("pg_cron_jobs", "Scheduled pg_cron jobs", "retention", "heavy",
           ("retention", "availability"), _p_cron_jobs,
           "Informational; cross-check that purge/retention jobs exist for every soft-delete table.",
           requires_fact="has_pg_cron"),
    _probe("timestamp_without_timezone", "Columns typed timestamp without time zone", "integrity", "heavy",
           ("integrity",), _p_ts_without_tz,
           "Migrate to timestamptz (`alter table <t> alter column <c> type timestamptz using <c> at time zone 'UTC'`)."),
    _probe("uuid_text_keys", "Primary keys typed text", "integrity", "heavy",
           ("integrity",), _p_text_keys,
           "Migrate the key to uuid (`… type uuid using <c>::uuid`) or bigint identity with a backfilled mapping."),
    _probe("partition_or_cluster_missing", "Large BigQuery tables without partitioning or clustering", "cost", "medium",
           ("availability",), _p_bq_partition,
           "Recreate the table partitioned by its time column and clustered by the dominant filter columns "
           "(`create table … partition by … cluster by … as select …`), then swap."),
    # ── coverage extension (2026-09-12): catalog, statistics and Supabase config ──────
    _probe("privileged_login_roles", "Login roles that are superuser or bypass RLS", "security", "cheap",
           ("access_control",), _p_privileged_roles,
           "`alter role <r> nosuperuser nobypassrls` in a migration; give the application a dedicated least-privilege "
           "role and keep the bootstrap role for migrations only. Rotate the credential if it was ever shipped to an app."),
    _probe("invalid_indexes", "Indexes marked invalid (failed concurrent build)", "integrity", "cheap",
           ("integrity", "availability"), _p_invalid_indexes,
           "`drop index concurrently <idx>` then `create index concurrently <idx> …` again in a migration run outside a "
           "transaction (`reindex index concurrently <idx>` on PG12+); fix the duplicate rows first if it is unique."),
    _probe("disabled_triggers", "Triggers left disabled", "integrity", "cheap",
           ("integrity", "audit_trail"), _p_disabled_triggers,
           "`alter table <t> enable trigger <trg>` (or `enable trigger all`) in a migration; if the trigger is obsolete, "
           "drop it instead of leaving it off. For a constraint trigger, re-validate the foreign key afterwards."),
    _probe("views_exposed_over_rls_tables", "anon/authenticated views over RLS-protected tables", "security", "cheap",
           ("access_control", "data_minimization"), _p_views_over_rls,
           "`alter view <v> set (security_invoker = true)` in a migration so the base tables' policies apply, or revoke "
           "select on the view from anon/authenticated; a materialized view needs its own grants review."),
    _probe("pii_readable_by_anon", "Plain-text personal data granted to anon / PUBLIC", "privacy", "cheap",
           ("data_minimization", "access_control"), _p_pii_anon,
           "`revoke select on public.<table> from anon` in a migration (expose a column-limited view if the app needs "
           "public reads); enable RLS with owner-scoped policies; encrypt or drop columns that are not needed."),
    _probe("idle_in_transaction_sessions", "Sessions idle in transaction longer than 5 minutes", "availability", "cheap",
           ("availability",), _p_idle_in_txn,
           "Set `idle_in_transaction_session_timeout = '60s'` on the application role (`alter role <r> set …`) and fix the "
           "code path that opens a transaction and awaits I/O; the pid/application_name names the client.",
           depends_on="data"),
    _probe("connection_saturation", "Connection usage vs max_connections", "availability", "cheap",
           ("availability",), _p_connection_saturation,
           "Route the app through the pooler (transaction mode) and cap its pool size; find the leaking client by "
           "application_name in pg_stat_activity; raise max_connections only after the pool is bounded.",
           depends_on="data"),
    _probe("cascade_delete_blast_radius", "ON DELETE CASCADE into large tables", "integrity", "medium",
           ("integrity",), _p_cascade_blast_radius,
           "Prefer `on delete restrict` (or soft delete on the parent) and an explicit, audited purge for the children; "
           "if cascade is intended, ensure an audit row is written for the parent delete and the child table is backed up.",
           depends_on="data"),
    _probe("large_tables_without_index", "Tables over 1M rows with no index at all", "performance", "medium",
           ("availability",), _p_large_no_index,
           "Add a primary key and `create index concurrently` on the columns the hot queries filter or join on "
           "(check pg_stat_statements for the predicates).", depends_on="data"),
    _probe("replication_slots_lagging", "Replication slots inactive or retaining WAL", "availability", "medium",
           ("availability",), _p_replication_slots,
           "Reconnect or remove the consumer; `select pg_drop_replication_slot('<slot>')` for an abandoned slot "
           "(operator action, not a migration); set `max_slot_wal_keep_size` so a dead slot cannot fill the disk.",
           depends_on="data"),
    _probe("updated_at_without_trigger", "updated_at columns not maintained by a trigger", "audit", "heavy",
           ("audit_trail",), _p_updated_at_no_trigger,
           "`create trigger set_updated_at before update on <t> for each row execute function moddatetime(updated_at)` "
           "(extension moddatetime) in a migration, so the timestamp is set by the database, not by every code path."),
    _probe("public_storage_buckets", "Public storage buckets", "security", "cheap",
           ("access_control", "data_minimization"), _p_storage_buckets,
           "Make the bucket private (`update storage.buckets set public = false`, in a migration) and serve files through "
           "signed URLs; keep a public bucket only for assets that are meant to be public and hold no personal data.",
           providers=["supabase"], depends_on="data"),
    # Management API config probes. No SQL: `config_path` names the GET path(s) under
    # /v1/projects/{ref}; run_probe passes the parser rows = [{path: payload, ...}] (see _cfg).
    # Configuration changes without DDL, so every one of these is depends_on="data".
    _probe("supabase_auth_config", "Auth service configuration weaknesses", "security", "medium",
           ("access_control",), _p_auth_config,
           "Change the setting in Authentication → Settings (or `PATCH /v1/projects/{ref}/config/auth`) and record the "
           "value in supabase/config.toml so it is reviewed like code.",
           dialects=["postgres"], providers=["supabase"], depends_on="data", config_path="/config/auth"),
    _probe("supabase_backups_pitr", "Backups and point-in-time recovery", "availability", "medium",
           ("availability",), _p_backups,
           "Enable the PITR add-on for the project (Settings → Add-ons); until then, take a `pg_dump` before every "
           "destructive migration and keep it outside the project.",
           dialects=["postgres"], providers=["supabase"], depends_on="data", config_path="/database/backups"),
    _probe("supabase_network_and_ssl", "Network restrictions and SSL enforcement", "security", "medium",
           ("access_control",), _p_network_ssl,
           "Apply a CIDR allow-list (Settings → Database → Network Restrictions, or "
           "`POST /v1/projects/{ref}/network-restrictions/apply`) covering only the app's egress addresses, and turn on "
           "SSL enforcement (`PUT /v1/projects/{ref}/ssl-enforcement`).",
           dialects=["postgres"], providers=["supabase"], depends_on="data",
           config_path=["/network-restrictions", "/ssl-enforcement"]),
    _probe("supabase_edge_functions_verify_jwt", "Edge functions deployed with verify_jwt=false", "security", "medium",
           ("access_control",), _p_edge_functions,
           "Redeploy with `--no-verify-jwt` removed (or `verify_jwt = true` in supabase/config.toml); for a genuine webhook "
           "target, verify the sender's signature in the handler and document it next to the function.",
           dialects=["postgres"], providers=["supabase"], depends_on="data", config_path="/functions"),
    # Supabase advisor lints: free, already computed by the platform. No SQL; run_probe calls advisors_fn.
    {"id": "supabase_advisor_security", "title": "Supabase security advisor lints", "category": "security",
     "tier": "cheap", "dialects": ["postgres"], "providers": ["supabase"], "evidence_kinds": ["access_control"],
     "sql": {}, "parse": None, "advisor_kind": "security",
     "remediation": "Follow the lint's remediation link; land the change as a migration."},
    {"id": "supabase_advisor_performance", "title": "Supabase performance advisor lints", "category": "performance",
     "tier": "cheap", "dialects": ["postgres"], "providers": ["supabase"], "evidence_kinds": ["availability"],
     "sql": {}, "parse": None, "advisor_kind": "performance",
     "remediation": "Follow the lint's remediation link; land the change as a migration."},
]

_BY_ID = {p["id"]: p for p in PROBES}


# ── catalog helpers ────────────────────────────────────────────────────────────────────

def probe_by_id(pid):
    return _BY_ID.get(str(pid or ""))


def probes_for(dialect, tier=None) -> list:
    return [p for p in PROBES if dialect in p.get("dialects", ()) and (tier is None or p.get("tier") == tier)]


def validate_catalog() -> list:
    """Problems with the catalog as strings (empty = healthy). Logged at import, asserted in tests."""
    problems = []
    seen = set()
    for p in PROBES:
        pid = p.get("id")
        if pid in seen:
            problems.append(f"duplicate probe id {pid}")
        seen.add(pid)
        if p.get("category") not in CATEGORIES:
            problems.append(f"{pid}: bad category {p.get('category')!r}")
        if p.get("tier") not in PROBE_TIERS:
            problems.append(f"{pid}: bad tier {p.get('tier')!r}")
        for d in p.get("dialects", ()):
            if d not in DIALECTS:
                problems.append(f"{pid}: bad dialect {d!r}")
        for k in p.get("evidence_kinds", ()):
            if k not in EVIDENCE_KINDS:
                problems.append(f"{pid}: bad evidence kind {k!r}")
        if not p.get("advisor_kind") and not callable(p.get("parse")):
            problems.append(f"{pid}: parse is not callable")
        for d, sql in (p.get("sql") or {}).items():
            try:
                assert_read_only(sql)
            except Exception as e:
                problems.append(f"{pid}/{d}: {e}")
    return problems


for _problem in validate_catalog():
    _log(f"catalog problem: {_problem}")


# ── execution ──────────────────────────────────────────────────────────────────────────

_IDENT_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _render_sql(sql, source) -> str:
    """Fill {project}/{dataset} for dialects whose INFORMATION_SCHEMA must be qualified.
    Identifiers are whitelisted so a config value can never smuggle SQL in."""
    if "{" not in sql:
        return sql
    cfg = (source or {}).get("config") or {}
    project = str(cfg.get("project_id") or (source or {}).get("ref") or "")
    dataset = str(cfg.get("dataset") or "")
    for name, val in (("project", project), ("dataset", dataset)):
        if "{%s}" % name in sql:
            if not _IDENT_RE.match(val):
                raise ValueError(f"source config.{name if name == 'dataset' else 'project_id'} missing or not an identifier")
            sql = sql.replace("{%s}" % name, val)
    return sql


def _call_parse(parse, rows, source, facts):
    try:
        n = len(inspect.signature(parse).parameters)
    except (TypeError, ValueError):
        n = 3
    return parse(rows, source, facts) if n >= 3 else parse(rows, source)


def run_probe(probe, source, query_fn=None, facts=None, advisors_fn=None) -> dict:  # noqa: FAIL_SOFT_ERROR — lint false positive: every error is captured into the result dict
    """Run one probe. Never raises: an error is captured in the result."""
    query_fn = query_fn or db_adapters.query
    advisors_fn = advisors_fn or db_adapters.supabase_advisors
    facts = facts if facts is not None else {}
    pid = (probe or {}).get("id")
    out = {"probe_id": pid, "findings": [], "ok": False, "error": None, "duration_ms": 0.0, "rows": 0}
    t0 = time.monotonic()
    try:
        if not probe:
            raise ValueError("no probe")
        if probe.get("advisor_kind"):
            lints = advisors_fn(source, probe["advisor_kind"]) or []
            out["rows"] = len(lints)
            findings = advisors_to_findings(lints, probe["advisor_kind"], source)
        elif probe.get("config_path"):
            # Management-API configuration probe: one GET per path, the parser receives
            # [{path: payload, ...}]. Only providers with a config API declare these.
            paths = probe["config_path"] if isinstance(probe["config_path"], (list, tuple)) else [probe["config_path"]]
            fetch = getattr(db_adapters, "supabase_config", None)
            if not fetch:
                raise LookupError("config probes need db_adapters.supabase_config")
            payload = {str(path): fetch(source, str(path)) for path in paths}
            out["rows"] = len(payload)
            findings = _call_parse(probe["parse"], [payload], source, facts) or []
        else:
            dialect = db_adapters.dialect_of(source)
            sql = (probe.get("sql") or {}).get(dialect)
            if not sql:
                raise LookupError(f"no {dialect} statement")
            sql = _render_sql(sql, source)
            assert_read_only(sql)
            rows = query_fn(source, sql) or []
            out["rows"] = len(rows)
            findings = _call_parse(probe["parse"], rows, source, facts) or []
        for f in findings:
            if isinstance(f, dict):
                if not f.get("remediation"):
                    f["remediation"] = str(probe.get("remediation") or "")[:2000]
                out["findings"].append(f)
        out["ok"] = True
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        _log(f"probe {pid} on {db_adapters.describe(source)}: {out['error']}")
    out["duration_ms"] = round((time.monotonic() - t0) * 1000, 2)
    return out


# ── execution engine: batches, waves, schema signature ─────────────────────────────────
#
# Round trips are the cost that matters. The Supabase Management API is rate limited per
# token and every wire connection pays a handshake, so thirty probes as thirty statements
# is the slow, expensive shape. Postgres lets us fold any number of SELECTs into ONE
# statement that returns each probe's rows as a JSON array:
#
#     select json_build_object('probe_a', (select coalesce(json_agg(t), '[]') from (<sql_a>) t),
#                              'probe_b', ...) as batch
#
# so a tier's structural probes cost one round trip. A batch that fails (one member's
# statement is wrong for this server) falls back to per-probe execution, so a single bad
# statement can never lose the wave. Probes gated on a fact run in a second wave after the
# fact-establishing ones. Units of work (batches and single probes) run on a small pool.

BATCH_ENABLED = str(os.environ.get("ORCH_DB_PROBE_BATCH", "true")).strip().lower() not in ("0", "false", "no", "off")
BATCH_SIZE = max(1, int(os.environ.get("ORCH_DB_PROBE_BATCH_SIZE", "12")))
PARALLEL_UNITS = max(1, int(os.environ.get("ORCH_DB_PROBE_PARALLEL", "4")))
_BATCH_DIALECTS = ("postgres",)
_BATCHABLE_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)

#: Probes whose findings move WITHOUT a DDL change (statistics, sessions, queue tables,
#: external advisors). Everything else depends on the schema alone and can be skipped when
#: the schema signature has not moved since the last successful full run.
_DATA_DEPENDENT = {
    "table_inventory_facts", "schema_migrations_latest", "sequence_headroom",
    "long_running_transactions", "unused_indexes", "dead_tuple_bloat", "vacuum_stale",
    "slow_query_classes", "pg_cron_jobs", "soft_delete_without_purge",
    "supabase_advisor_security", "supabase_advisor_performance",
}

#: One statement whose single value changes iff the schema (relations, columns, indexes,
#: constraints, policies, grants, functions, extensions) changes. Statistics are excluded on
#: purpose: a signature that moved with every insert would never let a scan be skipped.
SCHEMA_SIGNATURE_SQL = {
    "postgres": (
        "select md5(string_agg(x, '|' order by x)) as signature, count(*) as parts from ("
        "select 'rel:' || c.oid::text || ':' || n.nspname || '.' || c.relname || ':' || c.relkind::text "
        "|| ':' || c.relnatts::text || ':' || c.relrowsecurity::text || ':' || c.relforcerowsecurity::text "
        "|| ':' || coalesce(c.relacl::text, '') as x "
        "from pg_catalog.pg_class c join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname not in ('pg_catalog', 'information_schema', 'pg_toast') and n.nspname not like 'pg_temp%' "
        "union all "
        "select 'att:' || a.attrelid::text || ':' || a.attnum::text || ':' || a.attname || ':' || a.atttypid::text "
        "|| ':' || a.attnotnull::text || ':' || coalesce(a.atttypmod::text, '') || ':' || a.attisdropped::text "
        "from pg_catalog.pg_attribute a join pg_catalog.pg_class c on c.oid = a.attrelid "
        "join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
        "where a.attnum > 0 and n.nspname not in ('pg_catalog', 'information_schema', 'pg_toast') "
        "union all "
        "select 'idx:' || i.indexrelid::text || ':' || i.indrelid::text || ':' || i.indkey::text || ':' "
        "|| i.indisunique::text || ':' || i.indisvalid::text from pg_catalog.pg_index i "
        "union all "
        "select 'con:' || k.oid::text || ':' || k.conrelid::text || ':' || k.contype::text || ':' || k.convalidated::text "
        "|| ':' || coalesce(k.confdeltype::text, '') from pg_catalog.pg_constraint k "
        "union all "
        "select 'pol:' || p.oid::text || ':' || p.polrelid::text || ':' || p.polname || ':' || p.polcmd::text "
        "|| ':' || p.polpermissive::text || ':' || coalesce(p.polroles::text, '') from pg_catalog.pg_policy p "
        "union all "
        "select 'fn:' || f.oid::text || ':' || f.proname || ':' || f.prosecdef::text || ':' "
        "|| coalesce(f.proconfig::text, '') || ':' || coalesce(f.proacl::text, '') "
        "from pg_catalog.pg_proc f join pg_catalog.pg_namespace n on n.oid = f.pronamespace "
        "where n.nspname not in ('pg_catalog', 'information_schema') "
        "union all "
        "select 'ext:' || e.extname || ':' || e.extversion || ':' || e.extnamespace::text from pg_catalog.pg_extension e "
        "union all "
        "select 'trg:' || t.oid::text || ':' || t.tgrelid::text || ':' || t.tgname || ':' || t.tgenabled::text "
        "from pg_catalog.pg_trigger t where not t.tgisinternal "
        "union all "
        "select 'role:' || r.oid::text || ':' || r.rolname || ':' || r.rolsuper::text || ':' || r.rolbypassrls::text "
        "|| ':' || r.rolcanlogin::text from pg_catalog.pg_roles r"
        ") s"
    ),
}


def schema_signature(source, query_fn=None):
    """The schema signature for `source`, or None when the dialect has none or the query
    fails. One cheap catalog round trip; never raises."""
    query_fn = query_fn or db_adapters.query
    sql = SCHEMA_SIGNATURE_SQL.get(db_adapters.dialect_of(source))
    if not sql:
        return None
    try:
        assert_read_only(sql)
        rows = query_fn(source, sql) or []
        if rows and isinstance(rows[0], dict) and rows[0].get("signature"):
            return "%s:%s" % (rows[0]["signature"], rows[0].get("parts") or 0)
    except Exception as e:
        _log(f"schema_signature on {db_adapters.describe(source)}: {type(e).__name__}: {str(e)[:200]}")
    return None


def probe_depends_on(probe) -> str:
    """'data' when the probe's findings can move without DDL, else 'schema'."""
    return str(probe.get("depends_on") or ("data" if probe.get("id") in _DATA_DEPENDENT else "schema"))


def _batchable(probe, dialect) -> bool:
    if probe.get("advisor_kind") or probe.get("requires_fact"):
        return False
    sql = (probe.get("sql") or {}).get(dialect)
    return bool(sql) and dialect in _BATCH_DIALECTS and bool(_BATCHABLE_RE.match(sql)) and "{" not in sql


def _batch_sql(members, dialect) -> str:
    parts = []
    for probe in members:
        sql = str(probe["sql"][dialect]).strip().rstrip(";").strip()
        parts.append("'%s', (select coalesce(json_agg(t), '[]'::json) from (%s) t)" % (probe["id"], sql))
    # ::text — the Management API parses JSON in JavaScript, where a bigint (a
    # pg_stat_statements queryid, a relation oid) loses precision past 2^53 and changes a
    # fingerprint. As text it reaches Python intact and json.loads keeps every digit.
    return "select json_build_object(" + ", ".join(parts) + ")::text as batch"


def _coerce_batch(rows) -> dict:
    """The one-row/one-column batch result as {probe_id: [rows]} whatever the transport
    handed back (a parsed object, or JSON text)."""
    if not rows or not isinstance(rows[0], dict):
        raise ValueError("batch returned no row")
    val = rows[0].get("batch")
    if val is None and len(rows[0]) == 1:
        val = next(iter(rows[0].values()))
    if isinstance(val, (str, bytes)):
        val = json.loads(val)
    if not isinstance(val, dict):
        raise ValueError("batch value is %s, not an object" % type(val).__name__)
    return val


def _finish_probe_result(out, probe, findings, t0, rows_n):
    out["rows"] = rows_n
    for f in findings or []:
        if isinstance(f, dict):
            if not f.get("remediation"):
                f["remediation"] = str(probe.get("remediation") or "")[:2000]
            out["findings"].append(f)
    out["ok"] = True
    out["duration_ms"] = round((time.monotonic() - t0) * 1000, 2)
    return out


def run_batch(members, source, query_fn=None, facts=None) -> list:
    """Run several SQL probes as ONE statement; per-probe fallback when the batch fails.
    Returns one result dict per member, in member order. Never raises."""
    query_fn = query_fn or db_adapters.query
    facts = facts if facts is not None else {}
    dialect = db_adapters.dialect_of(source)
    t0 = time.monotonic()
    try:
        sql = _batch_sql(members, dialect)
        assert_read_only(sql)
        payload = _coerce_batch(query_fn(source, sql) or [])
    except Exception as e:
        _log(f"batch of {len(members)} on {db_adapters.describe(source)} fell back to per-probe: "
             f"{type(e).__name__}: {str(e)[:200]}")
        return [run_probe(p, source, query_fn=query_fn, facts=facts) for p in members]
    elapsed = round((time.monotonic() - t0) * 1000 / max(1, len(members)), 2)
    results = []
    for probe in members:
        pid = probe["id"]
        out = {"probe_id": pid, "findings": [], "ok": False, "error": None, "duration_ms": elapsed, "rows": 0,
               "batched": True}
        try:
            rows = payload.get(pid)
            if rows is None:
                raise LookupError("batch result lacks this probe")
            rows = db_adapters._truncate(list(rows))
            findings = _call_parse(probe["parse"], rows, source, facts) or []
            _finish_probe_result(out, probe, findings, t0, len(rows))
            out["duration_ms"] = elapsed
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
            _log(f"probe {pid} (batched) on {db_adapters.describe(source)}: {out['error']}")
        results.append(out)
    return results


def run_all(source, query_fn=None, tiers=PROBE_TIERS, advisors_fn=None, capabilities=None,
            probe_ids=None, skip_probe_ids=None, batch=None, parallel=None) -> dict:
    """Run every applicable probe; dedup findings by fingerprint keeping the most severe.

    Skips: wrong dialect/provider, tier not requested, capability known absent, required
    fact not established, id not in `probe_ids` (when given) or in `skip_probe_ids`.
    Batchable statements run as one round trip per BATCH_SIZE; units run on a small pool in
    two waves (fact producers first). Results keep catalog order. Never raises."""
    source = source or {}
    tiers = tuple(tiers or PROBE_TIERS)
    batch = BATCH_ENABLED if batch is None else bool(batch)
    parallel = PARALLEL_UNITS if parallel is None else max(1, int(parallel))
    dialect = db_adapters.dialect_of(source)
    provider = str(source.get("provider") or "")
    caps = capabilities if capabilities is not None else (source.get("capabilities") or {})
    only = set(probe_ids) if probe_ids is not None else None
    skip = set(skip_probe_ids or ())
    facts, skipped, by_fp = {}, [], {}
    results_by_id = {}
    wave1, wave2 = [], []
    for probe in PROBES:
        pid = probe["id"]
        if probe.get("tier") not in tiers:
            continue
        if dialect not in probe.get("dialects", ()):
            continue
        if probe.get("providers") and provider not in probe["providers"]:
            continue
        if (only is not None and pid not in only) or pid in skip:
            skipped.append({"probe_id": pid, "reason": "not selected this cycle"})
            continue
        cap = probe.get("requires_capability")
        if cap and cap in caps and not caps.get(cap):
            skipped.append({"probe_id": pid, "reason": f"capability {cap} absent"})
            continue
        (wave2 if probe.get("requires_fact") else wave1).append(probe)

    def _units(probes):
        units, pending = [], []
        for probe in probes:
            if batch and _batchable(probe, dialect):
                pending.append(probe)
                if len(pending) >= BATCH_SIZE:
                    units.append(("batch", list(pending)))
                    pending = []
            else:
                units.append(("single", probe))
        if pending:
            units.append(("batch", pending))
        return units

    def _run_unit(unit):
        kind, payload = unit
        if kind == "batch":
            return run_batch(payload, source, query_fn=query_fn, facts=facts)
        return [run_probe(payload, source, query_fn=query_fn, facts=facts, advisors_fn=advisors_fn)]

    def _run_wave(probes):
        units = _units(probes)
        if not units:
            return
        if parallel == 1 or len(units) == 1:
            outs = [_run_unit(u) for u in units]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(parallel, len(units))) as pool:
                outs = list(pool.map(_run_unit, units))
        for res_list in outs:
            for res in res_list:
                results_by_id[res["probe_id"]] = res

    _run_wave(wave1)
    ready = []
    for probe in wave2:
        fact = probe.get("requires_fact")
        if fact and not facts.get(fact):
            skipped.append({"probe_id": probe["id"], "reason": f"fact {fact} not established"})
            continue
        ready.append(probe)
    _run_wave(ready)

    results = [results_by_id[p["id"]] for p in PROBES if p["id"] in results_by_id]
    for res in results:
        for f in res["findings"]:
            fp = f.get("fingerprint")
            prev = by_fp.get(fp)
            if prev is None or SEVERITY_RANK.get(f.get("severity"), 0) > SEVERITY_RANK.get(prev.get("severity"), 0):
                by_fp[fp] = f
    findings = list(by_fp.values())
    return {"findings": findings, "results": results, "facts": facts, "skipped": skipped,
            "score": score(findings),
            "stats": {"run": len(results), "ok": sum(1 for r in results if r["ok"]),
                      "failed": sum(1 for r in results if not r["ok"]), "skipped": len(skipped),
                      "round_trips": len(_units(wave1)) + len(_units(ready)),
                      "duration_ms": round(sum(r["duration_ms"] for r in results), 2)}}


# ── supabase advisors -> findings ──────────────────────────────────────────────────────

_LINT_LEVEL = {"ERROR": "high", "WARN": "medium", "WARNING": "medium", "INFO": "low"}


def _advisor_kinds(name, kind):
    n = str(name or "").lower()
    if n.startswith("rls") or any(t in n for t in ("policy", "grant", "auth", "exposed", "security_definer",
                                                   "search_path", "public_schema", "role", "anon")):
        return ("access_control",)
    if n == "unindexed_foreign_keys":
        return ("availability", "integrity")
    if n in ("unused_index", "duplicate_index", "multiple_permissive_policies"):
        return ("availability",)
    if n == "no_primary_key":
        return ("integrity",)
    if n == "extension_in_public":
        return ("change_control",)
    return ("access_control",) if kind == "security" else ("availability",)


def advisors_to_findings(lints, kind, source) -> list:
    """Deterministic mapping of Supabase advisor lints to findings. Never raises."""
    category = "security" if kind == "security" else "performance"
    out = []
    for lint in lints or []:
        if not isinstance(lint, dict):
            continue
        try:
            name = str(lint.get("name") or "advisor_lint")
            meta = lint.get("metadata") or {}
            schema = str(meta.get("schema") or "")
            obj = str(meta.get("name") or "")
            sev = _LINT_LEVEL.get(str(lint.get("level") or "").upper(), "low")
            title = str(lint.get("title") or name)
            if obj:
                title = f"{title}: {schema + '.' if schema else ''}{obj}"
            kinds = _advisor_kinds(name, kind)
            if name == "extension_in_public":
                cat = "schema_drift"
            elif name == "unindexed_foreign_keys":
                cat = "performance"
            else:
                cat = category
            out.append(make_finding(f"supabase_advisor_{kind}", cat, sev, title,
                                    detail=str(lint.get("detail") or lint.get("description") or ""),
                                    object_schema=schema, object_name=obj, extra=name, evidence_kinds=kinds,
                                    remediation=str(lint.get("remediation") or ""),
                                    metrics={"lint": name, "level": lint.get("level"), "facing": lint.get("facing"),
                                             "type": meta.get("type"), "cache_key": lint.get("cache_key"),
                                             "categories": lint.get("categories")}))
        except Exception as e:
            _log(f"advisor lint skipped ({type(e).__name__}: {e})")
    return out


# ── scoring & summaries ────────────────────────────────────────────────────────────────

_SCORE_WEIGHT = {"critical": 25, "high": 10, "medium": 3, "low": 1}

#: The linear scorer's floor problem, observed live 2026-09-14: 100 - 3/medium means any
#: project past ~34 medium findings reads 0 forever, so fleet posture collapsed to "0-60"
#: and baselines/quartiles lost all resolution. Two fixes, both explainable:
#:  1. per (probe, severity) bucket, repeated instances decay logarithmically — the 10th
#:     table missing created_at is not a NEW failure mode, just more of the same one
#:     (weight × (1 + ln n): 1×w, 10×≈3.3w, 100×≈5.6w);
#:  2. D maps onto 0-100 through 100·e^(−D/80), which never hard-floors at 0, keeps strict
#:     ordering at every depth, and stays interpretable at the top (1 high ≈ 88, 1 crit ≈ 73).
_SCORE_DECAY_K = float(os.environ.get("ORCH_DB_SCORE_DECAY", "80"))


def score(findings) -> float:
    """0-100 posture score. Per-(probe,severity) demerits saturate logarithmically
    (repeats of one failure mode accrue weight × (1 + ln n)), then 100·e^(−D/80).
    Info and supporting findings do not count. Never exactly 0; always monotone in D."""
    buckets = {}
    for f in findings or []:
        if not isinstance(f, dict) or f.get("direction") == "supports":
            continue
        key = (f.get("probe_id") or "?", str(f.get("severity") or "info"))
        buckets[key] = buckets.get(key, 0) + 1
    d = sum(_SCORE_WEIGHT.get(sev, 0) * (1.0 + math.log(n)) for (probe, sev), n in buckets.items())
    return round(100.0 * math.exp(-d / _SCORE_DECAY_K), 1)


def summarize(findings, limit=8) -> str:
    """One line per finding, most severe first."""
    items = [f for f in (findings or []) if isinstance(f, dict)]
    items.sort(key=lambda f: (-SEVERITY_RANK.get(f.get("severity"), 0), f.get("direction") == "supports",
                              f.get("title", "")))
    lines = []
    for f in items[:max(0, int(limit))]:
        obj = ".".join(x for x in (f.get("object_schema"), f.get("object_name")) if x)
        tag = "+" if f.get("direction") == "supports" else "-"
        lines.append(f"[{str(f.get('severity', 'info')).upper()}] {tag} {f.get('title', '')}" + (f" ({obj})" if obj and obj not in f.get("title", "") else ""))
    if len(items) > limit:
        lines.append(f"… and {len(items) - limit} more")
    return "\n".join(lines)


if __name__ == "__main__":
    probs = validate_catalog()
    print(f"db_probes: {len(PROBES)} probes; {'OK' if not probs else probs}")
    for d in DIALECTS:
        ids = [p["id"] for p in probes_for(d)]
        if ids:
            print(f"  {d}: {', '.join(ids)}")
