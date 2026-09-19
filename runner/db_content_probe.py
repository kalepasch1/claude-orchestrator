#!/usr/bin/env python3
"""db_content_probe.py — governed, opt-in looks at DATA shape (not just schema).

Every other probe reads catalogs (grants, indexes, stats). Two questions need to glance at
values to be evidence-grade: "this column is named email — how many rows actually ARE
emails?" and "a column named password/token/secret exists — is anything stored in it?".
Both are answerable with COUNT-only statements: no row content ever leaves the database.

DOUBLE GATE — this is off unless BOTH hold:
  * env ORCH_DB_CONTENT_PROBE=1, and
  * the db_sources row carries config.content_probe=true (per-source, operator-set).

Everything passes db_steering_contract.assert_read_only() before running (the caller's
query path already enforces it, and we assert here too for direct use). Column/table
identifiers are whitelist-validated before interpolation; row VALUES are never selected
— only counts. Fail-soft everywhere.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db_steering_contract as C  # noqa: E402

ENABLED = os.environ.get("ORCH_DB_CONTENT_PROBE", "0") == "1"
MAX_COLS = int(os.environ.get("ORCH_DB_CONTENT_PROBE_MAX_COLS", "5"))
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: counts-only statements. The email-shape statement asks "how many rows are NOT shaped
#: like email" — never returning a value itself.
_SQL_META = ("select table_name, column_name from information_schema.columns "
             "where table_schema = 'public' and ("
             "lower(column_name) ~ '(^|_)(email|e_mail)(_|$)' "
             "or lower(column_name) ~ '(password|passwd|pwd|secret|token|api_key|apikey)(_|$)'"
             ") order by table_name limit 200")


def source_enabled(source):
    """Double gate: global env AND per-source config flag. Fail-soft False."""
    if not ENABLED:
        return False
    try:
        cfg = source.get("config") or {}
        if isinstance(cfg, str):
            import json
            cfg = json.loads(cfg or "{}")
        return bool(cfg.get("content_probe"))
    except Exception:
        return False


def collect(source, query_fn, max_cols=None):
    """Findings for email-shape mismatches and name-patterned secret columns, count-based
    only. query_fn is the adapter path (read-only enforced there too). Fail-soft []."""
    if not source_enabled(source):
        return []
    max_cols = MAX_COLS if max_cols is None else int(max_cols)
    assert C is not None
    C.assert_read_only(_SQL_META)  # belt: the caller's adapter also asserts
    findings = []
    try:
        meta = query_fn(source, _SQL_META) or []
    except Exception as e:
        print("db_content_probe: metadata read failed for %s: %s" % (source.get("ref"), str(e)[:120]))
        return []
    email_cols, secret_cols = [], []
    for r in meta[:200]:
        t, c = str(r.get("table_name") or ""), str(r.get("column_name") or "")
        if not (_IDENT_RE.match(t) and _IDENT_RE.match(c)):
            continue
        (secret_cols if re.search(r"(password|passwd|pwd|secret|token|api_key|apikey)(_|$)", c.lower())
         else email_cols).append((t, c))
    for table, col in secret_cols:
        sql = 'select count(*) as n from "public"."%s" where "%s" is not null' % (table, col)
        C.assert_read_only(sql)
        n = None
        try:
            rows = query_fn(source, sql) or []
            n = int((rows[0] or {}).get("n") or 0) if rows else None
        except Exception as e:
            print("db_content_probe: count failed for %s.%s: %s" % (table, col, str(e)[:80]))
        if n:
            findings.append(C.make_finding(
                "content_probe_secret_columns", "privacy",
                "high" if n > 1000 else "medium",
                "Column %s on public.%s holds %d non-null values — verify hashing/encryption at rest" % (col, table, n),
                object_schema="public", object_name=table, extra=col,
                evidence_kinds=("data_minimization",),
                metrics={"column": col, "non_null_rows": n},
                detail="A password/token/secret-named column with stored values; the probe only counted rows, never read one.",
                remediation="Verify the column stores hashed/encrypted values (e.g., crypt/pgcrypto or app-level hashing); if plaintext, rotate and re-encrypt."))
    for table, col in email_cols[:max_cols]:
        sql = ('select count(*) as n, count(*) filter (where "%s" !~ \'%s\' and "%s" is not null) as bad'
               ' from "public"."%s"' % (col, EMAIL_RE, col, table))
        C.assert_read_only(sql)
        try:
            rows = query_fn(source, sql) or []
        except Exception as e:
            print("db_content_probe: email shape count failed for %s.%s: %s" % (table, col, str(e)[:80]))
            continue
        if not rows:
            continue
        n, bad = int(rows[0].get("n") or 0), int(rows[0].get("bad") or 0)
        if n >= 50 and bad / max(1, n) > 0.01:
            pct = round(100.0 * bad / n, 1)
            findings.append(C.make_finding(
                "content_probe_email_shape", "integrity", "medium",
                "%s%% of %d rows in public.%s.%s are not email-shaped" % (pct, n, table, col),
                object_schema="public", object_name=table, extra=col,
                evidence_kinds=("integrity",), metrics={"column": col, "rows": n, "not_email": bad},
                detail="Column named like `email` holds non-email values; measured with counts only.",
                remediation="Move non-email payloads out or rename the column; add a CHECK constraint if the column should be email-shaped."))
    return findings
