#!/usr/bin/env python3
"""
db_memo.py — the legal-memo evidence engine of Database Steering.

WHY THIS EXISTS. db_steering.py runs deterministic probes against every linked
production database, continuously and at zero model cost, and stores what it finds as
fingerprinted, dated FINDINGS. Each finding declares which legal-memo ARGUMENT FAMILIES
it speaks to (`evidence_kinds`) and whether it supports or undermines them. Nobody
reads a thousand findings; counsel reads an argument. This module keeps INTERNAL memo
drafts current as the evidence accumulates, so that when the firm's own counsel needs
to argue "our records are kept contemporaneously as a regular business practice" or
"personal data is isolated at the row level", the argument is already drafted and every
sentence in it traces to a dated, fingerprinted fact the database itself produced.

It also steers. An argument that is being UNDERMINED is not only a legal exposure, it
is an engineering instruction: `steering_signals()` turns the heaviest undermined
arguments into short imperative lines the steering loop puts into every coder prompt
for that project, and the loop files remediation for the same facts. The memo and the
fix come from one ledger, so they cannot drift apart.

COST DISCIPLINE. Attaching evidence is pure bookkeeping (no model). Prose is drafted
by ONE costless-first model call per memo, and only when `evidence_hash()` — a digest
of the (finding, argument, direction, weight, status, last-seen date) set — differs
from the hash stored on the draft. The expert-corps gauntlet reviews a memo only when a
MATERIAL finding was added or resolved, at most once per memo per day. When no model
is available the deterministic `render_markdown()` is persisted so a memo always exists.

WHAT A MEMO IS NOT. Internal work product, never customer-facing, never legal advice,
never published: `publication_state` stays 'internal', nothing here notifies anyone,
nothing here writes an approval, and nothing here touches an application database —
only the fleet control-plane tables legal_memo_drafts / legal_memo_evidence via `db`.

HOLLOW-MEMO GUARD. A model draft is accepted only if it is at least
ORCH_DB_MEMO_MIN_BODY_CHARS long, cites at least one fingerprint, and every fingerprint
it cites is in the evidence ledger (invented cites are stripped first; if nothing valid
remains, the draft is refused). A refused draft never replaces a previous body: the row
is marked 'stale' and the next run tries again with the hash still unmatched.

Tunables (all ORCH_-prefixed env): ORCH_DB_MEMO_MAX_PER_RUN (3 memos drafted per run),
ORCH_DB_MEMO_GAUNTLET (default on), ORCH_DB_MEMO_GAUNTLET_MIN_INTERVAL_S (86400),
ORCH_DB_MEMO_MIN_BODY_CHARS (600), ORCH_DB_MEMO_PROMPT_CAP (12000), ORCH_DB_MEMO_NEED (7).

CLI: python3 db_memo.py [project] [--force] [--render <memo_kind>]
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402
from db_steering_contract import (  # noqa: E402
    EVIDENCE_DIRECTIONS, EVIDENCE_KINDS, EVIDENCE_TO_MEMOS, MEMO_KINDS, MEMO_STATUSES,
    SEVERITY_RANK, is_material,
)

MEMO_TABLE = "legal_memo_drafts"
EVIDENCE_TABLE = "legal_memo_evidence"
FINDINGS_TABLE = "db_findings"

MAX_PER_RUN = int(os.environ.get("ORCH_DB_MEMO_MAX_PER_RUN", "3"))
MIN_BODY_CHARS = int(os.environ.get("ORCH_DB_MEMO_MIN_BODY_CHARS", "600"))
PROMPT_CAP = int(os.environ.get("ORCH_DB_MEMO_PROMPT_CAP", "12000"))
MODEL_NEED = int(os.environ.get("ORCH_DB_MEMO_NEED", "7"))
GAUNTLET_CONTEXT_CAP = 6000
FP_LEN = 12  # the citation form: [fp:<first 12 hex of the finding fingerprint>]

CLOSING_LINE = ("Internal work product — not legal advice; evidence is machine-collected "
                "and should be verified before reliance.")

#: Undermining weight by severity. Supporting findings always weigh 1.0: a positive fact
#: is a positive fact, its "severity" is not a strength signal.
SEVERITY_WEIGHT = {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5, "info": 0.25}
SUPPORT_WEIGHT = 1.0

STRENGTHS = ("supported", "contested", "undermined", "unassessed")

#: Table names are usually plural (users, customers, profiles, payments): the optional
#: (e)s keeps the word boundary from missing them.
_PII_RE = re.compile(r"\b(pii|personal|user|profile|customer|member|patient|client|contact|"
                     r"email|phone|address|ssn|passport|dob|birth|name|payment|card|billing|"
                     r"identity|kyc|health|location)(?:es|s)?\b", re.I)
#: Tables that ARE model-call / usage logs (mirrors db_probes.AI_TABLE_PATTERN).
_AI_LOG_RE = re.compile(r"model_call|llm_|ai_call|completion|token_usage|usage_log|inference|prompt_log|"
                        r"agent_run|counsel_job|job_event", re.I)
_CITE_RE = re.compile(r"\[fp:([0-9a-fA-F]{6,64})\]")


# ── small helpers (mirroring legal_docket discipline) ──────────────────────────────────

def _s(v):
    """Coerce ANY model-returned value to a sliceable string (legal_docket lesson: the
    model intermittently returns a dict/list where a string was promised)."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return str(v)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_of(ts) -> str:
    return str(ts or "")[:10]


def _parse_ts(ts):
    try:
        s = str(ts or "").replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except Exception:
        return None


def _jsonish(v, default):
    """arguments/gauntlet columns come back as parsed JSON from PostgREST but as text from
    some fakes and older rows; accept both."""
    if v is None:
        return default
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return default


def _fp12(fp) -> str:
    return str(fp or "")[:FP_LEN]


def _memo_short(memo_kind: str) -> str:
    return str(memo_kind or "").split("_and_")[0]


def _env_flag(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() not in ("0", "false", "no", "off")


# ── argument routing ───────────────────────────────────────────────────────────────────
# probe_id -> {memo_kind: [argument_key, ...]}. Deterministic: no model decides where a
# fact goes. A probe absent here routes to the FIRST argument of the memo (never drop
# evidence); category-conditional probes are handled in argument_keys_for().
_AC = "access_control_and_least_privilege"
_RI = "records_integrity_and_audit_trail"
_DP = "data_protection_posture"
_OR = "operational_resilience"
_CC = "change_control_and_schema_governance"
_AI = "ai_use_disclosure_and_logging"

_RLS = {_AC: ["row_level_isolation"], _DP: ["pii_not_exposed"]}
ROUTES = {
    "rls_disabled_tables": _RLS,
    "rls_enabled_no_policy": _RLS,
    "pii_exposed_tables": _RLS,
    "anon_or_public_grants": {_AC: ["anon_surface_minimal"], _DP: ["pii_not_exposed"]},  # _DP only when PII-ish
    "security_definer_functions": {_AC: ["privileged_paths_bounded"]},
    "missing_audit_columns": {_RI: ["contemporaneous_records"]},  # _AI only when the table is an AI log
    "audit_trail_presence": {_RI: ["regular_practice"], _AI: ["provenance_traceable"]},
    "unvalidated_constraints": {_RI: ["referential_integrity"]},
    "tables_without_primary_key": {_RI: ["referential_integrity"]},
    "unindexed_foreign_keys": {_RI: ["referential_integrity"], _OR: ["performance_headroom"]},
    "pii_columns_inventory": {_DP: ["pii_inventory_known"]},
    "soft_delete_without_purge": {_DP: ["retention_enforced"]},
    "pg_cron_jobs": {_DP: ["retention_enforced"]},
    "slow_query_classes": {_OR: ["performance_headroom"]},
    "unused_indexes": {_OR: ["performance_headroom"]},
    "dead_tuple_bloat": {_OR: ["maintenance_current"]},
    "vacuum_stale": {_OR: ["maintenance_current"]},
    "sequence_headroom": {_OR: ["maintenance_current"]},
    "long_running_transactions": {_OR: ["maintenance_current"]},
    "extensions_in_public": {_CC: ["schema_matches_migrations", "changes_reviewable"]},
    "ai_call_logging_presence": {_AI: ["model_calls_logged"]},
}
_PREFIX_ROUTES = (
    ("schema_migrations_", {_CC: ["schema_matches_migrations", "changes_reviewable"]}),
)


def _pii_ish(finding: dict) -> bool:
    f = finding or {}
    if "data_minimization" in (f.get("evidence_kinds") or []):
        return True
    metrics = f.get("metrics") or {}
    if isinstance(metrics, dict) and (metrics.get("pii") or metrics.get("pii_columns")):
        return True
    blob = " ".join(str(f.get(k) or "") for k in ("object_name", "title", "detail"))
    return bool(_PII_RE.search(blob))


def argument_keys_for(memo_kind: str, finding: dict) -> list:
    """Deterministically map a finding to the argument key(s) it speaks to in `memo_kind`.
    Always returns at least one key that exists in MEMO_KINDS[memo_kind]["arguments"]
    (the memo's first argument is the catch-all), except for two deliberate exclusions:
    a non-PII public grant is not evidence about personal-data exposure, and a business
    table without created_at is not evidence about AI-call logging (the finding still
    lives in the records-integrity memo, so nothing is lost)."""
    spec = MEMO_KINDS.get(memo_kind)
    if not spec:
        return []
    valid = list(spec["arguments"].keys())
    first = valid[0]
    f = finding or {}
    probe = str(f.get("probe_id") or "")
    category = str(f.get("category") or "")

    keys = None  # None = no rule spoke; [] = a rule deliberately excluded this memo
    if probe == "unindexed_foreign_keys":
        # The one probe whose meaning depends on category: an integrity finding is about
        # referential context, a performance finding is about headroom.
        if memo_kind == _RI:
            keys = [] if category == "performance" else ["referential_integrity"]
        elif memo_kind == _OR:
            keys = [] if category == "integrity" else ["performance_headroom"]
    elif probe == "anon_or_public_grants" and memo_kind == _DP:
        keys = ["pii_not_exposed"] if _pii_ish(f) else []
    elif probe == "missing_audit_columns" and memo_kind == _AI:
        # Only a model-call / usage log table lacking timestamps undermines "logged with
        # ... time"; invoices without created_at say nothing about AI use.
        keys = ["model_calls_logged"] if _AI_LOG_RE.search(str(f.get("object_name") or "")) else []
    elif probe in ROUTES:
        keys = ROUTES[probe].get(memo_kind)
    else:
        for prefix, route in _PREFIX_ROUTES:
            if probe.startswith(prefix):
                keys = route.get(memo_kind)
                break
    if keys is None:
        # advisor:* lints, unknown probes, and known probes whose evidence kind also lands
        # them in a memo the table does not name: the memo's lead argument, with the one
        # category hint the contract gives us (availability -> failure_modes_known).
        if memo_kind == _OR and category == "availability" and "failure_modes_known" in valid:
            keys = ["failure_modes_known"]
        else:
            keys = [first]
    return [k for k in keys if k in valid]


def evidence_weight(finding: dict) -> float:
    f = finding or {}
    if str(f.get("status") or "open") == "resolved":
        return 0.0
    if f.get("direction") == "supports":
        return SUPPORT_WEIGHT
    return float(SEVERITY_WEIGHT.get(str(f.get("severity") or "info"), 0.25))


# ── persistence helpers ────────────────────────────────────────────────────────────────

def _one_row(res):
    """PostgREST echoes an insert as a one-element list; some fakes and older helpers
    return the dict. Normalise to a dict or None."""
    if isinstance(res, list):
        return res[0] if res and isinstance(res[0], dict) else None
    return res if isinstance(res, dict) else None


def _ensure_memo(project: str, memo_kind: str, cache: dict):
    """Return the draft row for (project, memo_kind), inserting the skeleton if absent."""
    key = (project, memo_kind)
    if key in cache:
        return cache[key]
    rows = db.select(MEMO_TABLE, {"select": "*", "project": f"eq.{project}",
                                  "memo_kind": f"eq.{memo_kind}", "limit": "1"}) or []
    row = rows[0] if rows else None
    if row is None:
        skeleton = {
            "project": project, "memo_kind": memo_kind,
            "title": MEMO_KINDS[memo_kind]["title"],
            "arguments": [], "evidence_count": 0,
            "status": "draft", "publication_state": "internal",
            "updated_at": _now_iso(),
        }
        row = _one_row(db.insert(MEMO_TABLE, skeleton))
        if not row:  # 409: a concurrent attach won the race — read theirs
            rows = db.select(MEMO_TABLE, {"select": "*", "project": f"eq.{project}",
                                          "memo_kind": f"eq.{memo_kind}", "limit": "1"}) or []
            row = rows[0] if rows else None
    if row is not None:
        cache[key] = row
    return row


def _upsert_evidence(memo_id, finding: dict, argument_key: str) -> bool:
    direction = finding.get("direction") if finding.get("direction") in EVIDENCE_DIRECTIONS else "undermines"
    weight = evidence_weight(finding)
    note = None
    if str(finding.get("status") or "") == "resolved":
        note = "resolved %s" % _date_of(finding.get("resolved_at") or finding.get("last_seen_at"))
    existing = db.select(EVIDENCE_TABLE, {"select": "id,direction,weight", "memo_id": f"eq.{memo_id}",
                                          "finding_id": f"eq.{finding['id']}",
                                          "argument_key": f"eq.{argument_key}", "limit": "1"}) or []
    if existing:
        cur = existing[0]
        try:
            same = (abs(float(cur.get("weight") or 0) - weight) < 1e-9 and cur.get("direction") == direction)
        except Exception:
            same = False
        if not same:
            db.update(EVIDENCE_TABLE, {"id": cur["id"]}, {"weight": weight, "direction": direction, "note": note})
        return True
    row = db.insert(EVIDENCE_TABLE, {"memo_id": memo_id, "finding_id": finding["id"],
                                     "argument_key": argument_key, "direction": direction,
                                     "weight": weight, "note": note})
    if row is None:  # lost a race on the unique key; the other writer's row stands
        return True
    return True


def attach_evidence(project: str, findings: list) -> dict:
    """Attach db_findings ROWS (with id) to every memo argument they speak to. Pure
    bookkeeping, no model. Resolved findings keep their row with weight 0 so a memo can
    say "was a gap, closed on <date>". Fail-soft: returns what it managed."""
    touched, n_rows = [], 0
    cache = {}
    try:
        for f in findings or []:
            if not isinstance(f, dict) or not f.get("id"):
                continue
            for kind in (f.get("evidence_kinds") or []):
                if kind not in EVIDENCE_KINDS:
                    continue
                for memo_kind in EVIDENCE_TO_MEMOS.get(kind, []):
                    keys = argument_keys_for(memo_kind, f)
                    if not keys:
                        continue
                    try:
                        memo = _ensure_memo(project, memo_kind, cache)
                    except Exception as e:
                        print(f"db_memo: ensure memo {project}/{memo_kind} failed: {type(e).__name__}: {str(e)[:120]}")
                        continue
                    if not memo or not memo.get("id"):
                        continue
                    for key in keys:
                        try:
                            if _upsert_evidence(memo["id"], f, key):
                                n_rows += 1
                        except Exception as e:
                            print(f"db_memo: evidence upsert {memo_kind}/{key} for finding {f.get('id')} failed: "
                                  f"{type(e).__name__}: {str(e)[:120]}")
                    if memo_kind not in touched:
                        touched.append(memo_kind)
    except Exception as e:
        print(f"db_memo: attach_evidence({project}) aborted: {type(e).__name__}: {str(e)[:160]}")
    return {"memos_touched": touched, "evidence_rows": n_rows}


# ── ledger + hash ──────────────────────────────────────────────────────────────────────

def _chunks(seq, n=100):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _load_ledger(memo_id) -> list:
    """Evidence rows joined to their findings, most severe first, gaps before positives.
    Each entry carries everything the prompt, the renderer and the hash need."""
    ev = db.select_all(EVIDENCE_TABLE, {"select": "id,finding_id,argument_key,direction,weight,note",
                                        "memo_id": f"eq.{memo_id}"}, order="created_at.asc,id.asc") or []
    if not ev:
        return []
    fids = sorted({str(e.get("finding_id")) for e in ev if e.get("finding_id")})
    findings = {}
    for chunk in _chunks(fids):
        rows = db.select(FINDINGS_TABLE, {
            "select": "id,probe_id,category,severity,fingerprint,title,detail,object_schema,object_name,"
                      "metrics,status,first_seen_at,last_seen_at,resolved_at,remediation,direction",
            "id": "in.(%s)" % ",".join(chunk), "limit": str(len(chunk))}) or []
        for r in rows:
            findings[str(r.get("id"))] = r
    ledger = []
    for e in ev:
        f = findings.get(str(e.get("finding_id")))
        if not f:
            continue  # finding deleted; cascade will remove the evidence row
        try:
            weight = float(e.get("weight") or 0)
        except Exception:
            weight = 0.0
        metrics = f.get("metrics") or {}
        try:
            metrics_excerpt = json.dumps(metrics, sort_keys=True, default=str)[:200]
        except Exception:
            metrics_excerpt = str(metrics)[:200]
        ledger.append({
            "finding_id": str(f.get("id")),
            "fp": _fp12(f.get("fingerprint")),
            "fingerprint": str(f.get("fingerprint") or ""),
            "title": str(f.get("title") or "")[:200],
            "detail": str(f.get("detail") or "")[:400],
            "probe_id": str(f.get("probe_id") or ""),
            "severity": str(f.get("severity") or "info"),
            "direction": e.get("direction") or f.get("direction") or "undermines",
            "argument_key": str(e.get("argument_key") or ""),
            "weight": weight,
            "object": ".".join(x for x in (f.get("object_schema"), f.get("object_name")) if x),
            "first_seen": _date_of(f.get("first_seen_at")),
            "last_seen": _date_of(f.get("last_seen_at")),
            "last_seen_at": f.get("last_seen_at"),
            "status": str(f.get("status") or "open"),
            "resolved_at": _date_of(f.get("resolved_at")),
            "metrics": metrics_excerpt,
            "remediation": str(f.get("remediation") or "")[:400],
        })
    ledger.sort(key=lambda x: (-SEVERITY_RANK.get(x["severity"], 0),
                               0 if x["direction"] == "undermines" else 1,
                               x["status"] != "open", x["fp"]))
    return ledger


def _hash_ledger(ledger: list) -> str:
    items = sorted((x["finding_id"], x["argument_key"], x["direction"], "%.2f" % x["weight"],
                    x["status"], x["last_seen"]) for x in ledger)
    blob = json.dumps(items, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def evidence_hash(memo_id) -> str:
    """sha256 over the sorted (finding, argument, direction, weight, status, last-seen date)
    set: a changed evidence set — or a resolved gap — changes it; nothing else does."""
    try:
        return _hash_ledger(_load_ledger(memo_id))
    except Exception as e:
        print(f"db_memo: evidence_hash({memo_id}) failed: {type(e).__name__}: {str(e)[:120]}")
        return ""


# ── argument scoring ───────────────────────────────────────────────────────────────────

def score_arguments(memo_kind: str, ledger: list) -> list:
    """[{key, claim, strength, supports:[fp], undermines:[fp], resolved:[fp], weight_for,
    weight_against}] — deterministic. supported: nothing active undermines it;
    undermined: active gaps outweigh support; contested: both sides carry weight;
    unassessed: no evidence at all."""
    out = []
    for key, claim in MEMO_KINDS.get(memo_kind, {}).get("arguments", {}).items():
        sup, und, res, w_for, w_against = [], [], [], 0.0, 0.0
        for x in ledger:
            if x["argument_key"] != key:
                continue
            if x["status"] == "resolved" or x["weight"] <= 0:
                if x["direction"] == "undermines":
                    res.append(x["fp"])
                continue
            if x["direction"] == "supports":
                sup.append(x["fp"]); w_for += x["weight"]
            else:
                und.append(x["fp"]); w_against += x["weight"]
        if w_for == 0 and w_against == 0:
            strength = "unassessed"
        elif w_against == 0:
            strength = "supported"
        elif w_against > w_for:
            strength = "undermined"
        else:
            strength = "contested"
        out.append({"key": key, "claim": claim, "strength": strength,
                    "supports": sup, "undermines": und, "resolved": res,
                    "weight_for": round(w_for, 2), "weight_against": round(w_against, 2)})
    return out


# ── rendering (deterministic) ──────────────────────────────────────────────────────────

def render_markdown(memo_row: dict, evidence_rows: list) -> str:
    """Model-free rendering with the same section structure the model is asked for. Used by
    the CLI and persisted as the body whenever the model cannot be reached, so a memo
    always exists. `evidence_rows` are ledger entries from _load_ledger()."""
    memo_row = memo_row or {}
    memo_kind = memo_row.get("memo_kind") or ""
    spec = MEMO_KINDS.get(memo_kind, {})
    ledger = list(evidence_rows or [])
    args = _jsonish(memo_row.get("arguments"), None) or score_arguments(memo_kind, ledger)
    title = memo_row.get("title") or spec.get("title") or memo_kind
    project = memo_row.get("project") or ""
    lines = [f"# {title}", "",
             f"Project: {project} · Memo: {memo_kind} · Internal draft · Rendered {_now_iso()[:10]} (deterministic)", "",
             "## Question presented", "",
             f"Does the machine-collected evidence from the production data layer of `{project}` support "
             f"the following positions, and where does it undermine them?", ""]
    for a in args:
        lines.append(f"- **{a['key']}** — {a['claim']}")
    lines += ["", "## Short answer", ""]
    for a in args:
        n_s, n_u, n_r = len(a.get("supports") or []), len(a.get("undermines") or []), len(a.get("resolved") or [])
        lines.append(f"- {a['key']}: **{a['strength'].upper()}** — {n_s} supporting, {n_u} undermining"
                     + (f", {n_r} closed" if n_r else "") + " finding(s).")
    lines += ["", "## Evidence", ""]
    if ledger:
        lines.append("| fp | severity | direction | argument | finding | object | first seen | last seen | status |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for x in ledger:
            status = x["status"] + (f" {x['resolved_at']}" if x["status"] == "resolved" and x.get("resolved_at") else "")
            lines.append(f"| [fp:{x['fp']}] | {x['severity']} | {x['direction']} | {x['argument_key']} | "
                         f"{x['title'].replace('|', '/')} | {x['object'] or '-'} | {x['first_seen']} | "
                         f"{x['last_seen']} | {status} |")
    else:
        lines.append("_No evidence attached yet._")
    lines += ["", "## Gaps and remediation", ""]
    gaps = [x for x in ledger if x["direction"] == "undermines" and x["status"] != "resolved" and x["weight"] > 0]
    if gaps:
        for x in gaps:
            lines.append(f"- ({x['severity']}) {x['title']}" + (f" — {x['remediation']}" if x["remediation"] else "")
                         + f" [fp:{x['fp']}]")
    else:
        lines.append("- No open gaps in the ledger.")
    closed = [x for x in ledger if x["direction"] == "undermines" and x["status"] == "resolved"]
    if closed:
        lines.append("")
        lines.append("Closed gaps:")
        for x in closed:
            lines.append(f"- {x['title']} — was a gap, closed on {x['resolved_at'] or x['last_seen']} [fp:{x['fp']}]")
    lines += ["", "## What would change the conclusion", ""]
    for a in args:
        if a["strength"] in ("undermined", "contested"):
            lines.append(f"- {a['key']}: resolving the {len(a.get('undermines') or [])} undermining finding(s) "
                         f"would move this to supported.")
        elif a["strength"] == "supported":
            lines.append(f"- {a['key']}: any new undermining finding in this argument family would reopen it.")
        else:
            lines.append(f"- {a['key']}: no probe has reported on this yet; it is unassessed, not established.")
    lines += ["", CLOSING_LINE, ""]
    return "\n".join(lines)


# ── model drafting ─────────────────────────────────────────────────────────────────────

def _build_prompt(memo_row: dict, ledger: list, args: list) -> str:
    memo_kind = memo_row.get("memo_kind") or ""
    spec = MEMO_KINDS.get(memo_kind, {})
    head = [
        "You are drafting an INTERNAL legal memorandum for the firm's own counsel. It is work product, "
        "not advice to a client, and it will be relied on to decide what to argue and what to fix.",
        "",
        f"MEMO: {spec.get('title') or memo_kind}",
        f"PROJECT (production system under review): {memo_row.get('project')}",
        "",
        "ARGUMENTS TO ASSESS (key — claim — deterministic strength from the evidence weights):",
    ]
    for a in args:
        head.append(f"- {a['key']} — {a['claim']} — {a['strength']} "
                    f"(for {a['weight_for']}, against {a['weight_against']})")
    head += [
        "",
        "RULES — a memo that breaks any of these is a failing answer:",
        "1. Every factual assertion must end with a citation of the form [fp:<12-hex>] naming a ledger "
        "entry below. You may cite ONLY fingerprints that appear in the ledger. 'We believe' or 'it "
        "appears' language without a cite is a failing answer.",
        "2. Do not speculate about facts not in the ledger. If the ledger is silent on something, say it "
        "is unassessed.",
        "3. For each argument, name concretely what evidence would change your conclusion.",
        "4. Treat a resolved finding as 'was a gap, closed on <date>' — closure is itself evidence of practice.",
        "5. Write for a lawyer: precise, unhedged where the evidence is clear, explicit where it is not.",
        "",
        "STRUCTURE (markdown, exactly these headings, in this order):",
        "# <Heading>",
        "## Question presented",
        "## Short answer  — one sentence per argument, starting with the argument key and its strength",
        "## Evidence  — bullets; each bullet ends with [fp:...]",
        "## Gaps and remediation  — from undermining findings, quoting the remediation text, each with [fp:...]",
        "## What would change the conclusion  — per argument",
        f"Then, as the final line, verbatim: {CLOSING_LINE}",
        "",
        "EVIDENCE LEDGER (most severe first; fp is the citation token):",
    ]
    prompt = "\n".join(head) + "\n"
    for x in ledger:
        line = (f"- fp:{x['fp']} | {x['severity']} | {x['direction']} | arg={x['argument_key']} | "
                f"{x['title']} | object={x['object'] or '-'} | first_seen={x['first_seen']} | "
                f"last_seen={x['last_seen']} | status={x['status']}"
                + (f" (closed {x['resolved_at']})" if x["status"] == "resolved" else "")
                + (f" | metrics={x['metrics']}" if x["metrics"] and x["metrics"] != "{}" else "")
                + (f" | remediation={x['remediation']}" if x["remediation"] and x["direction"] == "undermines" else "")
                + "\n")
        if len(prompt) + len(line) > PROMPT_CAP - 200:
            prompt += f"- ... ledger truncated at prompt cap ({len(ledger)} entries total)\n"
            break
        prompt += line
    prompt += "\nWrite the memo now.\n"
    return prompt


def _call_model(prompt: str):
    """ONE costless-first completion. Raises on any failure so the caller can fall back."""
    import model_policy, model_gateway
    prov, model, _ = model_policy.choose("review", agentic=False, need=MODEL_NEED)
    r = model_gateway.complete(prov, model, prompt)
    text = _s(r.get("text") if isinstance(r, dict) else r).strip()
    return text, prov, model


def validate_draft(text: str, ledger: list):
    """HOLLOW-MEMO GUARD. Returns (body, None) when acceptable, (None, reason) otherwise.
    Invalid citations are stripped before judging; the closing line is appended if the
    model forgot it (that is a formatting slip, not hollowness)."""
    body = _s(text).strip()
    if not body:
        return None, "empty draft"
    valid_fps = {x["fp"].lower() for x in ledger if x.get("fp")}
    full_fps = {x["fingerprint"].lower() for x in ledger if x.get("fingerprint")}
    cited, invalid = [], []

    def _is_valid(tok: str) -> bool:
        t = tok.lower()
        if t in valid_fps:
            return True
        return any(f.startswith(t) or t.startswith(f) for f in full_fps if len(t) >= 8)

    def _sub(m):
        tok = m.group(1)
        if _is_valid(tok):
            cited.append(tok.lower()[:FP_LEN])
            return m.group(0)
        invalid.append(tok)
        return ""

    body = _CITE_RE.sub(_sub, body)
    body = re.sub(r"[ \t]+\n", "\n", body)
    if invalid:
        print(f"db_memo: stripped {len(invalid)} invented citation(s): {invalid[:5]}")
    if not cited:
        return None, "zero valid citations" + (f" ({len(invalid)} invented)" if invalid else "")
    if len(body) < MIN_BODY_CHARS:
        return None, f"draft too short ({len(body)} < {MIN_BODY_CHARS} chars)"
    if CLOSING_LINE not in body:
        body = body.rstrip() + "\n\n" + CLOSING_LINE + "\n"
    return body, None


def _thesis_of(body: str) -> str:
    """First line of the Short answer section, else the first non-heading sentence."""
    m = re.search(r"^##\s*Short answer[^\n]*\n(.*?)(?=^##\s|\Z)", body, re.M | re.S)
    block = m.group(1) if m else body
    for line in block.splitlines():
        s = line.strip().lstrip("-*• ").strip()
        if s and not s.startswith("#"):
            return s[:500]
    return ""


def _rebuild_one(memo: dict, force: bool) -> dict:
    memo_id, memo_kind, project = memo.get("id"), memo.get("memo_kind"), memo.get("project")
    ledger = _load_ledger(memo_id)
    h = _hash_ledger(ledger)
    if not force and h and h == (memo.get("evidence_hash") or ""):
        return {"memo_kind": memo_kind, "outcome": "skipped", "reason": "evidence unchanged"}
    args = score_arguments(memo_kind, ledger)
    last_evidence_at = None
    for x in ledger:
        ts = x.get("last_seen_at")
        if ts and (last_evidence_at is None or str(ts) > str(last_evidence_at)):
            last_evidence_at = ts
    n_active = sum(1 for x in ledger if x["weight"] > 0)
    common = {"arguments": args, "evidence_count": n_active, "publication_state": "internal",
              "last_evidence_at": last_evidence_at, "updated_at": _now_iso()}

    body, prov, model, reason = None, None, None, None
    if ledger:
        try:
            text, prov, model = _call_model(_build_prompt(memo, ledger, args))
            body, reason = validate_draft(text, ledger)
        except Exception as e:
            reason = f"model unavailable: {type(e).__name__}: {str(e)[:120]}"
            print(f"db_memo: {project}/{memo_kind} {reason} — persisting deterministic rendering")
            body, prov, model = render_markdown({**memo, "arguments": args}, ledger), None, "deterministic"
    else:
        body, prov, model = render_markdown({**memo, "arguments": args}, ledger), None, "deterministic"
        reason = "no evidence; deterministic rendering"

    if body is None:
        # Hollow draft. Never let it replace real prose; if there is no prose yet, the
        # deterministic rendering stands in so a memo exists.
        print(f"db_memo: {project}/{memo_kind} rejected model draft: {reason}")
        if memo.get("body"):
            db.update(MEMO_TABLE, {"id": memo_id}, {**common, "status": "stale"})
            return {"memo_kind": memo_kind, "outcome": "rejected", "reason": reason, "model_calls": 1}
        body, prov, model = render_markdown({**memo, "arguments": args}, ledger), None, "deterministic"
        patch = {**common, "body": body, "thesis": _thesis_of(body), "status": "stale",
                 "model_provider": None, "model_name": model, "drafted_at": _now_iso()}
        db.update(MEMO_TABLE, {"id": memo_id}, patch)
        return {"memo_kind": memo_kind, "outcome": "rejected_fallback_deterministic", "reason": reason,
                "model_calls": 1}

    deterministic = (model == "deterministic")
    patch = {**common, "body": body, "thesis": _thesis_of(body),
             # A deterministic body does not consume the hash: the next run tries the model
             # again while the evidence is unchanged, rather than freezing a template.
             "evidence_hash": None if deterministic else h,
             "status": "draft", "drafted_at": _now_iso(),
             "model_provider": prov, "model_name": model}
    db.update(MEMO_TABLE, {"id": memo_id}, patch)
    try:
        import fleet_rag
        fleet_rag.index_document("legal_memo", f"{project}:{memo_kind}", body, project=project)
    except Exception as e:
        print(f"db_memo: fleet_rag index of {project}/{memo_kind} failed: {type(e).__name__}: {str(e)[:100]}")
    return {"memo_kind": memo_kind, "outcome": "deterministic" if deterministic else "drafted",
            "reason": reason, "model_calls": 0 if (deterministic and not ledger) else 1,
            "chars": len(body), "arguments": {a["key"]: a["strength"] for a in args}}


def rebuild_if_changed(project: str, force: bool = False, max_memos: int = None) -> dict:
    """Redraft every memo of `project` whose evidence hash moved (or all, with force), at
    most `max_memos` per run. One model call per redrafted memo, none otherwise."""
    max_memos = MAX_PER_RUN if max_memos is None else int(max_memos)
    out = {"project": project, "checked": 0, "drafted": 0, "skipped": 0, "rejected": 0,
           "deterministic": 0, "memos": []}
    try:
        memos = db.select(MEMO_TABLE, {"select": "*", "project": f"eq.{project}",
                                       "order": "updated_at.asc", "limit": "50"}) or []
    except Exception as e:
        print(f"db_memo: rebuild_if_changed({project}) could not list memos: {type(e).__name__}: {str(e)[:120]}")
        return out
    budget = max_memos
    for memo in memos:
        if budget <= 0:
            out["memos"].append({"memo_kind": memo.get("memo_kind"), "outcome": "deferred", "reason": "per-run cap"})
            continue
        out["checked"] += 1
        try:
            r = _rebuild_one(memo, force)
        except Exception as e:
            print(f"db_memo: rebuild of {project}/{memo.get('memo_kind')} failed: {type(e).__name__}: {str(e)[:160]}")
            r = {"memo_kind": memo.get("memo_kind"), "outcome": "error", "reason": f"{type(e).__name__}: {str(e)[:120]}"}
        out["memos"].append(r)
        oc = r.get("outcome")
        if oc == "skipped":
            out["skipped"] += 1
        else:
            budget -= 1
            if oc == "drafted":
                out["drafted"] += 1
            elif oc == "deterministic":
                out["deterministic"] += 1
            elif oc and oc.startswith("rejected"):
                out["rejected"] += 1
    return out


# ── gauntlet ───────────────────────────────────────────────────────────────────────────

def should_gauntlet(memo_row: dict, findings_delta: list) -> bool:
    """Material new/resolved finding AND the memo has not been reviewed within the minimum
    interval AND the env switch is not off. Cheap, pure, testable."""
    if not _env_flag("ORCH_DB_MEMO_GAUNTLET", "true"):
        return False
    if not any(is_material(f) for f in (findings_delta or []) if isinstance(f, dict)):
        return False
    last = _parse_ts((memo_row or {}).get("gauntlet_at"))
    if last is None:
        return True
    min_interval = float(os.environ.get("ORCH_DB_MEMO_GAUNTLET_MIN_INTERVAL_S", "86400") or 86400)
    return (time.time() - last) >= min_interval


def gauntlet_review(memo_row: dict, findings_delta: list):
    """Expert-corps review of a memo after a material evidence change. Never blocks the
    loop: any failure is logged and None returned. Stores the result on the draft."""
    try:
        if not should_gauntlet(memo_row, findings_delta):
            return None
        memo_id = memo_row.get("id")
        title = memo_row.get("title") or MEMO_KINDS.get(memo_row.get("memo_kind"), {}).get("title", "")
        body = memo_row.get("body") or ""
        if not body:
            return None
        ledger = _load_ledger(memo_id)
        ledger_txt = "\n".join(f"- fp:{x['fp']} {x['severity']} {x['direction']} {x['argument_key']}: {x['title']} "
                               f"[{x['status']}]" for x in ledger)
        context = (f"PROJECT: {memo_row.get('project')}\nINTERNAL MEMO DRAFT (machine-evidenced):\n\n{body}"
                   f"\n\nEVIDENCE LEDGER:\n{ledger_txt}")[:GAUNTLET_CONTEXT_CAP]
        question = (f"Review the internal memo '{title}'. For each argument: is the stated strength justified "
                    f"by the cited evidence, which claims are overstated, and what additional evidence would "
                    f"the firm need before relying on it?")
        agg = None
        try:
            import gauntlet
            agg = gauntlet.run(question, context=context, vertical="data")
            if agg and isinstance(agg, dict) and agg.get("error"):
                print(f"db_memo: gauntlet returned error for {memo_id}: {_s(agg.get('error'))[:120]}")
                agg = None
        except Exception as e:
            print(f"db_memo: gauntlet unavailable on {memo_id}: {type(e).__name__}: {str(e)[:120]}")
        if not agg:
            try:
                import committees
                agg = committees.review("legal_memo", memo_id, title, context, app=memo_row.get("project"))
            except Exception as e:
                print(f"db_memo: committees fallback failed on {memo_id}: {type(e).__name__}: {str(e)[:120]}")
        if not agg or not isinstance(agg, dict):
            return None
        try:
            stored = json.loads(json.dumps(agg, default=str)[:20000])
        except Exception:
            stored = {"summary": _s(agg)[:8000]}
        patch = {"gauntlet": stored, "gauntlet_at": _now_iso(), "updated_at": _now_iso(),
                 "publication_state": "internal"}
        if _s(agg.get("verdict")).strip() or _s(agg.get("position") or agg.get("opinion")).strip():
            patch["status"] = "reviewed"
        db.update(MEMO_TABLE, {"id": memo_id}, patch)
        return agg
    except Exception as e:
        print(f"db_memo: gauntlet_review failed: {type(e).__name__}: {str(e)[:160]}")
        return None


# ── read models for the brief / web API ────────────────────────────────────────────────

def memo_summary(project: str) -> list:
    out = []
    try:
        rows = db.select(MEMO_TABLE, {"select": "memo_kind,title,status,evidence_count,arguments,updated_at,"
                                                "drafted_at,gauntlet_at",
                                      "project": f"eq.{project}", "order": "memo_kind.asc", "limit": "50"}) or []
        for r in rows:
            strengths = {"supported": 0, "contested": 0, "undermined": 0, "unassessed": 0}
            for a in _jsonish(r.get("arguments"), []) or []:
                s = (a or {}).get("strength")
                if s in strengths:
                    strengths[s] += 1
            out.append({"memo_kind": r.get("memo_kind"), "title": r.get("title"), "status": r.get("status"),
                        "evidence_count": r.get("evidence_count") or 0, "strengths": strengths,
                        "updated_at": r.get("updated_at"), "drafted_at": r.get("drafted_at"),
                        "gauntlet_at": r.get("gauntlet_at")})
    except Exception as e:
        print(f"db_memo: memo_summary({project}) failed: {type(e).__name__}: {str(e)[:120]}")
    return out


def steering_signals(project: str, max_lines: int = 6, max_chars: int = 200) -> list:
    """Imperative lines for the coder brief, one per UNDERMINED argument, heaviest first.
    e.g. 'records_integrity: 3 findings undermine contemporaneous_records — add created_at
    timestamptz default now() to every table touched by a migration'."""
    lines = []
    try:
        memos = db.select(MEMO_TABLE, {"select": "id,memo_kind,arguments", "project": f"eq.{project}",
                                       "limit": "50"}) or []
        cands = []
        for m in memos:
            args = _jsonish(m.get("arguments"), []) or []
            undermined = [a for a in args if (a or {}).get("strength") == "undermined"]
            if not undermined:
                continue
            ledger = _load_ledger(m.get("id"))
            for a in undermined:
                key = a.get("key")
                gaps = [x for x in ledger if x["argument_key"] == key and x["direction"] == "undermines"
                        and x["weight"] > 0 and x["status"] != "resolved"]
                if not gaps:
                    continue
                total = sum(x["weight"] for x in gaps)
                top = gaps[0]  # ledger is most-severe-first
                action = top["remediation"] or f"close: {top['title']}"
                n = len(gaps)
                line = (f"{_memo_short(m.get('memo_kind'))}: {n} finding{'s' if n != 1 else ''} undermine "
                        f"{key} ({top['title']}) — {action}")
                cands.append((total, SEVERITY_RANK.get(top["severity"], 0), line[:max_chars]))
        cands.sort(key=lambda t: (-t[0], -t[1], t[2]))
        lines = [c[2] for c in cands[:max_lines]]
    except Exception as e:
        print(f"db_memo: steering_signals({project}) failed: {type(e).__name__}: {str(e)[:120]}")
    return lines


# ── orchestration ──────────────────────────────────────────────────────────────────────

def _projects_with_open_findings() -> list:
    rows = db.select_all(FINDINGS_TABLE, {"select": "project", "status": "in.(open,acknowledged)"},
                         order="project.asc,id.asc") or []
    seen = []
    for r in rows:
        p = r.get("project")
        if p and p not in seen:
            seen.append(p)
    return sorted(seen)


def run(project: str = None, limit: int = None, force: bool = False) -> dict:
    """Rebuild changed memos for one project or for every project with open findings."""
    results = {}
    try:
        projects = [project] if project else _projects_with_open_findings()
        if limit:
            projects = projects[:int(limit)]
        for p in projects:
            results[p] = rebuild_if_changed(p, force=force)
    except Exception as e:
        print(f"db_memo: run failed: {type(e).__name__}: {str(e)[:160]}")
    return results


def _cli(argv):
    force = "--force" in argv
    render = None
    if "--render" in argv:
        i = argv.index("--render")
        render = argv[i + 1] if i + 1 < len(argv) else None
    positional = [a for a in argv if not a.startswith("--") and a != render]
    project = positional[0] if positional else None
    if render:
        if not project:
            print("usage: db_memo.py <project> --render <memo_kind>")
            return 2
        rows = db.select(MEMO_TABLE, {"select": "*", "project": f"eq.{project}",
                                      "memo_kind": f"eq.{render}", "limit": "1"}) or []
        if not rows:
            print(f"no memo {render} for {project}")
            return 1
        print(render_markdown(rows[0], _load_ledger(rows[0]["id"])))
        return 0
    print(json.dumps(run(project, force=force), indent=2, default=str))
    return 0


if __name__ == "__main__":
    import single_instance
    _owned, _deadline = single_instance.guard("db_memo", interval_s=600)
    if not _owned:
        print(json.dumps({"skipped": "db_memo already running"}))
        raise SystemExit(0)
    try:
        raise SystemExit(_cli(sys.argv[1:]))
    finally:
        if _deadline is not None:
            _deadline.cancel()
