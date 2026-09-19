#!/usr/bin/env python3
"""
db_steering_contract.py — the shared vocabulary of Database Steering.

Pure and dependency-free on purpose: db_adapters, db_probes, db_steering, db_memo,
db_registry, the web API and every test import their constants and validators from
here, so a category, severity, evidence kind or provider is spelled exactly once.

WHAT DATABASE STEERING IS (2026-09-12). The fleet steers CODE continuously — gates,
verdict cards, an expert corps, swarm-filed remediation. Its only database control was
rls_guard: one COUNT(*) per app, once a day, over a hand-typed list of eight Supabase
refs (two live app databases were not on it). Database Steering makes every linked
database a first-class, continuously reviewed subject:

  * db_registry   — discovers and registers sources (Supabase auto-discovered through
                    the Management API; AWS / Google / any Postgres, MySQL, BigQuery,
                    Snowflake ... linked by the operator with a credential REFERENCE).
  * db_adapters   — one read-only `query(source, sql)` across providers.
  * db_probes     — a catalog of deterministic, zero-model-cost probes (catalog SQL,
                    pg_stat_statements, Supabase advisor lints) that yield FINDINGS.
  * db_steering   — the loop: run due probes, dedup by fingerprint, snapshot posture,
                    write the per-project steering brief coder agents read, file
                    remediation through the swarm filer, hand deltas to db_memo.
  * db_memo       — attaches every finding to the legal-memo argument it supports or
                    undermines and keeps internal memo drafts current; the expert-corps
                    gauntlet reviews only material changes.

COST RULE. Probes never call a model. Models are used only (a) to draft memo prose when
the evidence set actually changed and (b) in the gauntlet for material changes, both
costless-first through model_policy. That is what makes perpetual real-time review
affordable: the signal is SQL, the intelligence is applied once per NEW fact.

SAFETY RULE. Every statement sent to an app database is a read. `assert_read_only()` is
the chokepoint; an adapter that receives anything else raises before any network I/O.
"""
from __future__ import annotations

import hashlib
import json
import re

CONTRACT_VERSION = "dbsteer-2026.09.1"

# ── providers & dialects ───────────────────────────────────────────────────────────────
PROVIDERS = (
    "supabase", "postgres", "mysql",
    "aws_rds", "aws_aurora", "aws_redshift",
    "gcp_cloudsql", "gcp_alloydb", "gcp_bigquery",
    "azure_postgres", "azure_mysql",
    "neon", "planetscale", "cockroachdb", "snowflake", "mongodb", "other",
)
DIALECTS = ("postgres", "mysql", "bigquery", "snowflake", "mongodb", "other")

# The dialect a provider speaks unless the source row says otherwise.
PROVIDER_DEFAULT_DIALECT = {
    "supabase": "postgres", "postgres": "postgres", "neon": "postgres", "cockroachdb": "postgres",
    "aws_rds": "postgres", "aws_aurora": "postgres", "aws_redshift": "postgres",
    "gcp_cloudsql": "postgres", "gcp_alloydb": "postgres", "azure_postgres": "postgres",
    "mysql": "mysql", "planetscale": "mysql", "azure_mysql": "mysql",
    "gcp_bigquery": "bigquery", "snowflake": "snowflake", "mongodb": "mongodb", "other": "other",
}

SOURCE_STATUSES = ("active", "paused", "unreachable", "inactive")

# ── findings ───────────────────────────────────────────────────────────────────────────
SEVERITIES = ("info", "low", "medium", "high", "critical")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}
CATEGORIES = ("security", "privacy", "integrity", "audit", "performance",
              "availability", "retention", "schema_drift", "cost", "ai_governance")
FINDING_STATUSES = ("open", "resolved", "suppressed", "acknowledged")

# Probe cost tiers decide cadence: cheap every run, medium hourly, heavy daily.
PROBE_TIERS = ("cheap", "medium", "heavy")
PROBE_TIER_MIN_INTERVAL_S = {"cheap": 0, "medium": 3600, "heavy": 86400}

# ── legal-memo evidence model ──────────────────────────────────────────────────────────
# An EVIDENCE KIND is the argument family a finding speaks to. Probes declare which kinds
# they inform; db_memo maps each kind to the memo it belongs in and the argument key it
# supports or undermines. Deterministic — no model decides where a fact goes.
EVIDENCE_KINDS = (
    "access_control",      # RLS, grants, roles, security-definer surfaces
    "audit_trail",         # event/audit tables, timestamps, immutability, actor columns
    "data_minimization",   # PII footprint, exposure of personal data
    "retention",           # deleted_at without purge, unbounded logs, retention windows
    "integrity",           # primary keys, foreign keys, orphans, constraints
    "availability",        # bloat, vacuum, slow queries, sequence exhaustion
    "change_control",      # schema drift vs. migrations, unreviewed DDL
    "ai_logging",          # model-call logs, disclosure, provenance tables
)

MEMO_KINDS = {
    "access_control_and_least_privilege": {
        "title": "Access control and least privilege in the production data layer",
        "evidence_kinds": ("access_control",),
        "arguments": {
            "row_level_isolation": "Tenant and user data are isolated at the row level by policy, not by application discipline alone.",
            "anon_surface_minimal": "The anonymous / public surface of the database is limited to intentionally public reference data.",
            "privileged_paths_bounded": "Privileged execution paths (security-definer functions, service roles) are enumerated and bounded.",
        },
    },
    "records_integrity_and_audit_trail": {
        "title": "Records integrity and audit trail (business-records foundation)",
        "evidence_kinds": ("audit_trail", "integrity"),
        "arguments": {
            "contemporaneous_records": "Records are created contemporaneously with the events they describe (created_at / actor columns present and populated).",
            "regular_practice": "Record-keeping is a regular, systematic practice of the business (event tables exist for every material workflow).",
            "tamper_evidence": "Material records are append-only or otherwise tamper-evident.",
            "referential_integrity": "Relationships between records are enforced by the database, so a record cannot silently lose its context.",
        },
    },
    "data_protection_posture": {
        "title": "Data protection posture: minimization, exposure and retention",
        "evidence_kinds": ("data_minimization", "retention", "access_control"),
        "arguments": {
            "pii_inventory_known": "Personal data is inventoried: the tables and columns holding it are known and reviewed.",
            "pii_not_exposed": "Personal data is never readable through anonymous or over-broad grants.",
            "retention_enforced": "Retention and deletion are enforced mechanically (purge jobs, bounded logs), not by intention.",
        },
    },
    "operational_resilience": {
        "title": "Operational resilience of the data layer",
        "evidence_kinds": ("availability", "integrity"),
        "arguments": {
            "performance_headroom": "Hot paths have index coverage and no query class dominates the database.",
            "maintenance_current": "Vacuum, bloat and sequence headroom are within safe bounds.",
            "failure_modes_known": "The failure modes that would interrupt service are enumerated and tracked to closure.",
        },
    },
    "change_control_and_schema_governance": {
        "title": "Change control and schema governance",
        "evidence_kinds": ("change_control",),
        "arguments": {
            "schema_matches_migrations": "The live schema matches the versioned migration history; no unreviewed DDL is in production.",
            "changes_reviewable": "Every schema change is attributable to a reviewed, versioned migration.",
        },
    },
    "ai_use_disclosure_and_logging": {
        "title": "AI use: logging, provenance and disclosure readiness",
        "evidence_kinds": ("ai_logging", "audit_trail"),
        "arguments": {
            "model_calls_logged": "Every model call that touches customer work product is logged with model, route, cost and time.",
            "provenance_traceable": "AI-assisted outputs can be traced to their inputs, authorities and reviewers.",
        },
    },
}

# Reverse index: evidence kind -> memo kinds that use it.
EVIDENCE_TO_MEMOS = {}
for _mk, _spec in MEMO_KINDS.items():
    for _ek in _spec["evidence_kinds"]:
        EVIDENCE_TO_MEMOS.setdefault(_ek, []).append(_mk)

MEMO_STATUSES = ("draft", "reviewed", "stale")
EVIDENCE_DIRECTIONS = ("supports", "undermines")

# ── read-only chokepoint ───────────────────────────────────────────────────────────────
# Write/DDL shapes, matched as statement fragments (keyword + what must follow it) so a
# column called updated_at, n_tup_del or a function called set_config never trips it.
_WRITE_SHAPES = re.compile(
    r"\b(?:insert\s+into|update\s+[\w.\"]+\s+set\b|delete\s+from|merge\s+into|"
    r"drop\s+(?:table|index|view|schema|function|policy|role|trigger|type|sequence|extension|database)|"
    r"alter\s+(?:table|index|view|schema|function|policy|role|type|sequence|system|database|default)|"
    r"create\s+(?:or\s+replace\s+)?(?:table|index|view|schema|function|policy|role|trigger|type|sequence|extension|database|materialized)|"
    r"truncate\s+(?:table\s+)?[\w.\"]+|grant\s+\w+|revoke\s+\w+|vacuum\b|reindex\b|cluster\s+[\w.\"]+|"
    r"copy\s+[\w.\"(]+|call\s+[\w.\"]+\s*\(|refresh\s+materialized|lock\s+table|"
    r"set\s+(?:local\s+|session\s+)?[\w.]+\s*(?:=|to)\b|reset\s+\w+|"
    r"security\s+definer|reassign\s+owned|discard\s+\w+|notify\s+\w+|listen\s+\w+|"
    r"prepare\s+\w+\s+as|execute\s+\w+|deallocate\s+\w+|do\s+\$\$|"
    r"begin\b|commit\b|rollback\b|savepoint\s+\w+|checkpoint\b|load\s+'|import\s+foreign)",
    re.I)
_LEADING = re.compile(r"^\s*(?:--[^\n]*\n|/\*.*?\*/\s*)*\s*(with|select|show|explain|describe|table)\b",
                      re.I | re.S)


class ReadOnlyViolation(ValueError):
    """Raised before any I/O when a probe statement is not a plain read."""


def assert_read_only(sql: str) -> str:  # noqa: FAIL_SOFT_ERROR — a guard that fails soft is not a guard
    """Return `sql` if it is a single read statement; raise ReadOnlyViolation otherwise.

    Deliberately strict: it rejects any statement whose first keyword is not
    WITH/SELECT/SHOW/EXPLAIN/DESCRIBE/TABLE, any embedded statement separator, and any
    write/DDL shape ANYWHERE in the text — a false rejection costs one probe, a false
    acceptance writes to a production database while its owners are editing it.
    """
    text = str(sql or "")
    if not text.strip():
        raise ReadOnlyViolation("empty statement")
    if ";" in text.rstrip().rstrip(";"):
        raise ReadOnlyViolation("multiple statements are not allowed")
    if not _LEADING.match(text):
        raise ReadOnlyViolation("statement must begin with WITH/SELECT/SHOW/EXPLAIN/DESCRIBE/TABLE")
    # String literals, quoted identifiers and comments cannot carry a write shape.
    stripped = re.sub(r"'(?:[^']|'')*'", "''", text)
    stripped = re.sub(r'"(?:[^"]|"")*"', '""', stripped)
    stripped = re.sub(r"--[^\n]*", "", stripped)
    stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.S)
    m = _WRITE_SHAPES.search(stripped)
    if m:
        raise ReadOnlyViolation("write/DDL shape %r is not allowed in a probe" % m.group(0))
    return text


# ── finding constructor ────────────────────────────────────────────────────────────────

def fingerprint(probe_id: str, object_schema: str = "", object_name: str = "", extra: str = "") -> str:
    """Stable identity of a finding: the probe plus the object it is about. Metrics are
    NOT part of it — a slow query that gets slower is the same finding, updated, not a
    new one. `extra` disambiguates when one object can carry several instances (e.g. a
    table with two unindexed foreign keys)."""
    blob = "|".join([CONTRACT_VERSION.split(".")[0], str(probe_id), str(object_schema or ""),
                     str(object_name or ""), str(extra or "")])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def make_finding(probe_id: str, category: str, severity: str, title: str, *,  # noqa: FAIL_SOFT_ERROR — a probe with a vocabulary typo must fail its own test, not poison the table
                 detail: str = "", object_schema: str = "", object_name: str = "",
                 metrics=None, evidence_kinds=(), remediation: str = "", extra: str = "",
                 direction: str = "undermines") -> dict:
    """Build and validate one finding dict. Raises ValueError on an unknown vocabulary
    value so a typo in a probe fails its own unit test instead of poisoning the table."""
    if category not in CATEGORIES:
        raise ValueError("unknown category %r" % (category,))
    if severity not in SEVERITIES:
        raise ValueError("unknown severity %r" % (severity,))
    kinds = tuple(evidence_kinds or ())
    for k in kinds:
        if k not in EVIDENCE_KINDS:
            raise ValueError("unknown evidence kind %r" % (k,))
    if direction not in EVIDENCE_DIRECTIONS:
        raise ValueError("unknown direction %r" % (direction,))
    if not str(title or "").strip():
        raise ValueError("a finding needs a title")
    return {
        "probe_id": str(probe_id),
        "category": category,
        "severity": severity,
        "fingerprint": fingerprint(probe_id, object_schema, object_name, extra),
        "title": str(title)[:300],
        "detail": str(detail or "")[:4000],
        "object_schema": str(object_schema or "")[:200],
        "object_name": str(object_name or "")[:300],
        "metrics": _jsonable(metrics or {}),
        "evidence_kinds": list(kinds),
        "remediation": str(remediation or "")[:2000],
        # `supports`: the fact is GOOD for the memo argument (e.g. "audit table present");
        # `undermines`: the fact is a gap. Most probes report gaps; positive probes exist
        # so a memo can also cite what is in order, not only what is missing.
        "direction": direction,
    }


def _jsonable(obj):
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return {"repr": str(obj)[:500]}


def worst_severity(findings) -> str:
    best = "info"
    for f in findings or []:
        s = (f or {}).get("severity", "info")
        if SEVERITY_RANK.get(s, 0) > SEVERITY_RANK[best]:
            best = s
    return best


def is_material(finding) -> bool:
    """Material findings file remediation and can trigger a gauntlet review."""
    return SEVERITY_RANK.get((finding or {}).get("severity", "info"), 0) >= SEVERITY_RANK["high"]


def credential_ref_is_reference(ref: str) -> bool:
    """A credential reference names WHERE a secret lives; it never IS the secret.
    Accepted forms: env:NAME, keychain:NAME, doppler:PATH, onepassword:op://..., vault:<uuid>,
    file:/abs/path. A raw DSN/URL/password-shaped string is refused."""
    s = str(ref or "").strip()
    if not s:
        return True  # no credential (e.g. Supabase via the fleet token) is fine
    if re.match(r"^(env|keychain|doppler|onepassword|vault|file):", s):
        return not re.search(r"://[^/\s]*:[^/\s]*@", s)  # no user:pass@ inside a ref
    return False
