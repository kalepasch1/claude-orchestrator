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

import inspect
import json
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
        out.append(make_finding("unindexed_foreign_keys", "performance", sev,
                                f"Foreign key {con} on {schema}.{table} has no covering index", object_schema=schema,
                                object_name=table, extra=con, evidence_kinds=("availability", "integrity"),
                                metrics={"constraint": con, "referenced_table": _s(_v(r, "referenced_table")),
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
                                    detail="Rows cannot be shown to have been recorded contemporaneously."))
        elif not has_updated and has_upd_grants:
            out.append(make_finding("missing_audit_columns", "audit", "low",
                                    f"Updatable table {schema}.{table} has created_at but no updated_at",
                                    object_schema=schema, object_name=table, evidence_kinds=("audit_trail",),
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
                    "rc.reltuples::bigint as referenced_rows, c.reltuples::bigint as est_rows "
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


def run_all(source, query_fn=None, tiers=PROBE_TIERS, advisors_fn=None, capabilities=None) -> dict:
    """Run every applicable probe in catalog order; dedup findings by fingerprint keeping the
    most severe. Skips: wrong dialect/provider, tier not requested, capability known absent,
    required fact not established. Never raises."""
    source = source or {}
    tiers = tuple(tiers or PROBE_TIERS)
    dialect = db_adapters.dialect_of(source)
    provider = str(source.get("provider") or "")
    caps = capabilities if capabilities is not None else (source.get("capabilities") or {})
    facts, results, skipped, by_fp = {}, [], [], {}
    for probe in PROBES:
        pid = probe["id"]
        if probe.get("tier") not in tiers:
            continue
        if dialect not in probe.get("dialects", ()):
            continue
        if probe.get("providers") and provider not in probe["providers"]:
            continue
        cap = probe.get("requires_capability")
        if cap and cap in caps and not caps.get(cap):
            skipped.append({"probe_id": pid, "reason": f"capability {cap} absent"})
            continue
        fact = probe.get("requires_fact")
        if fact and not facts.get(fact):
            skipped.append({"probe_id": pid, "reason": f"fact {fact} not established"})
            continue
        res = run_probe(probe, source, query_fn=query_fn, facts=facts, advisors_fn=advisors_fn)
        results.append(res)
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


def score(findings) -> float:
    """0-100 posture score: 100 minus 25/critical, 10/high, 3/medium, 1/low (floor 0);
    info and supporting findings do not count."""
    total = 100
    for f in findings or []:
        if not isinstance(f, dict) or f.get("direction") == "supports":
            continue
        total -= _SCORE_WEIGHT.get(f.get("severity"), 0)
    return float(max(0, total))


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
