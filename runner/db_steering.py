#!/usr/bin/env python3
"""
db_steering.py — the Database Steering loop: perpetual, read-only, near-zero-cost review of
every linked database, turned into (1) steering for the coder agents, (2) swarm-filed
remediation, and (3) evidence for the legal-memo drafts db_memo keeps current.

WHY THIS IS A THOUSAND TIMES MORE REVIEW THAN BEFORE, IN NUMBERS THAT CAN BE CHECKED.
Before: rls_guard — 1 probe x 8 hand-listed Supabase refs x 1 run/day = 8 facts/day, and
two live production databases were not on the list. Now: db_registry auto-discovers every
Supabase project the fleet token can see (25 on 2026-09-12, 12 active) and any AWS /
Google / other database an operator links; db_probes runs ~25 deterministic probes per
Postgres source (catalog, pg_stat_statements, the free Supabase security + performance
advisor lints) with cheap probes every cycle (10 min), medium hourly, heavy daily. That
is on the order of 12 sources x ~15 cheap probes x 144 cycles = ~26k probe executions a
day, each yielding zero-to-many object-level facts, plus event detection (a finding that
appears, worsens or resolves between cycles) that a daily count could never see. No model
is consulted to produce any of it. Models are spent only on NEW facts: a memo is redrafted
when its evidence hash changes, and the expert-corps gauntlet reviews only material
changes, both routed costless-first. Cost therefore scales with how often the databases
CHANGE, not with how often they are looked at — which is what makes "real time" affordable.

HOW STEERING REACHES THE PEOPLE AND AGENTS EDITING THESE DATABASES, WITHOUT INTERRUPTING
THEM. Three channels, none of which touches a repo, a worktree, a session or an app DB:
  * `db_steering_briefs` — a <=2KB per-project brief ("3 public tables lack RLS: if you
    touch matters/engagements, add owner-scoped policies in the same migration") that
    prompt_assembler injects into every coder prompt for that project. Agents simply do
    the right thing on the next task; nobody is paged.
  * swarm remediation — material findings (high/critical, gaps) become ONE task per
    (project, probe) through swarm_enqueue, at swarm priority below all user-directed
    work, deduplicated by slug so a persistent gap is one ticket, not one per cycle.
  * memo evidence — every finding is handed to db_memo, which attaches it to the legal
    argument it supports or undermines and keeps the internal draft current.

SAFETY. Every statement crosses db_steering_contract.assert_read_only() inside the
adapter. The loop has a wall-clock budget per run (ORCH_DB_STEERING_BUDGET_S) and scans
the stalest source first, so no source starves and a slow one cannot wedge the cycle.
Failures are per-source and per-probe, logged, never raised. The loop writes only to the
fleet control plane.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402
import db_steering_contract as C  # noqa: E402
import db_registry  # noqa: E402

LOOP_TYPE = "db_steering"
LOOP_PROJECT = "claude-orchestrator"
LOOP_CADENCE_S = int(os.environ.get("ORCH_DB_STEERING_CADENCE_S", "600"))
BUDGET_S = float(os.environ.get("ORCH_DB_STEERING_BUDGET_S", "240"))
MAX_TASKS_PER_RUN = int(os.environ.get("ORCH_DB_STEERING_MAX_TASKS_PER_RUN", "3"))
#: Wall-clock budget for the memo-drafting phase that follows the scans. A costless local
#: model can take minutes per memo; without a cap one run could overlap the next cadence.
MEMO_BUDGET_S = float(os.environ.get("ORCH_DB_STEERING_MEMO_BUDGET_S", "300"))
#: How many open, material, still-unfiled findings are re-offered for remediation each
#: scan (findings first written by a manual `db_link scan --write`, or whose swarm task
#: was refused by release backpressure, would otherwise never be filed).
UNFILED_RETRY_LIMIT = int(os.environ.get("ORCH_DB_STEERING_UNFILED_RETRY_LIMIT", "200"))
BRIEF_MAX_CHARS = int(os.environ.get("ORCH_DB_STEERING_BRIEF_CHARS", "2000"))
BRIEF_CACHE_TTL_S = int(os.environ.get("ORCH_DB_STEERING_BRIEF_TTL_S", "300"))
CAPABILITIES_TTL_S = int(os.environ.get("ORCH_DB_CAPABILITIES_TTL_S", "86400"))
REMEDIATION_ENABLED = os.environ.get("ORCH_DB_STEERING_REMEDIATION", "true").lower() != "false"
FINDING_TOUCH_S = int(os.environ.get("ORCH_DB_FINDING_TOUCH_S", "3600"))
BULK_CHUNK = int(os.environ.get("ORCH_DB_BULK_CHUNK", "100"))
_brief_cache = {}


def _now_iso():
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _ts(value):
    """ISO/epoch -> epoch seconds; 0 on anything unparseable."""
    if not value:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        raw = str(value).replace("Z", "+00:00")
        return _dt.datetime.fromisoformat(raw).timestamp()
    except Exception:
        return 0.0


# ── loop registration ─────────────────────────────────────────────────────────────────

def ensure_loop_row(enabled=True):
    """Make sure the `loops` table carries a db_steering row so loops.py fires us.
    Idempotent; never raises."""
    try:
        rows = db.select("loops", {"select": "id,enabled", "type": "eq.%s" % LOOP_TYPE, "limit": "1"}) or []
        if rows:
            return rows[0]
        res = db.insert("loops", {"project": LOOP_PROJECT, "type": LOOP_TYPE,
                                  "cadence_seconds": LOOP_CADENCE_S, "enabled": bool(enabled),
                                  "config": {"loop": "db_steering"}})
        return res[0] if isinstance(res, list) and res else (res if isinstance(res, dict) else None)
    except Exception as e:
        print("db_steering: ensure_loop_row failed: %s: %s" % (type(e).__name__, str(e)[:120]))
        return None


# ── per-source scan ───────────────────────────────────────────────────────────────────

def _due_tiers(source, now=None):
    """Cheap always; medium/heavy when their last run is older than the tier interval.
    Timestamps live in source.capabilities.tiers so they travel with the row."""
    now = now or time.time()
    last = ((source.get("capabilities") or {}).get("tiers") or {})
    tiers = ["cheap"]
    for tier in ("medium", "heavy"):
        if now - _ts(last.get(tier)) >= C.PROBE_TIER_MIN_INTERVAL_S[tier]:
            tiers.append(tier)
    return tuple(tiers)


def _capabilities(source, adapters, now=None):
    caps = dict(source.get("capabilities") or {})
    now = now or time.time()
    if now - _ts(caps.get("probed_at")) < CAPABILITIES_TTL_S and caps.get("dialect"):
        return caps
    try:
        fresh = adapters.capabilities(source) or {}
    except Exception as e:
        print("db_steering: capabilities probe failed for %s: %s" % (source.get("label"), str(e)[:120]))
        fresh = {}
    caps.update(fresh)
    caps["probed_at"] = now
    return caps


def _repo_migration_drift(source, facts):
    """Fleet-side probe: compare the live schema_migrations record with the repo's
    supabase/migrations folder. Only the loop can do this (it has the checkout); it is
    the one probe that runs no SQL of its own. Returns a list of findings."""
    project = source.get("project")
    if not project or not facts:
        return []
    try:
        rows = db.select("projects", {"select": "repo_path", "name": "eq.%s" % project, "limit": "1"}) or []
    except Exception:
        rows = []
    repo = (rows[0].get("repo_path") if rows else None) or ""
    mig_dir = os.path.join(repo, "supabase", "migrations")
    if not repo or not os.path.isdir(mig_dir):
        return []
    try:
        files = sorted(f for f in os.listdir(mig_dir) if f.endswith(".sql"))
    except Exception:
        return []
    repo_versions = [re.match(r"^(\d{8,14})", f).group(1) for f in files if re.match(r"^(\d{8,14})", f)]
    live_latest = str(facts.get("schema_migrations_latest") or "")
    live_count = facts.get("schema_migrations_count")
    if not repo_versions or not live_latest:
        return []
    repo_latest = max(repo_versions)
    out = []
    if live_latest < repo_latest:
        pending = [v for v in repo_versions if v > live_latest]
        out.append(C.make_finding(
            "schema_drift_repo_ahead", "schema_drift", "medium" if len(pending) < 3 else "high",
            "%d repo migration(s) not applied to the live database" % len(pending),
            detail="repo latest %s, live latest %s; pending: %s" % (
                repo_latest, live_latest, ", ".join(pending[:10])),
            object_schema="supabase_migrations", object_name="schema_migrations",
            metrics={"repo_latest": repo_latest, "live_latest": live_latest, "pending": len(pending)},
            evidence_kinds=("change_control",),
            remediation="apply the pending migrations through the normal release path, or delete "
                        "the ones that were superseded; the live schema and the versioned history must agree"))
    elif live_latest > repo_latest:
        out.append(C.make_finding(
            "schema_drift_live_ahead", "schema_drift", "high",
            "live database carries a migration the repo does not have",
            detail="live latest %s is newer than repo latest %s — DDL was applied outside version control"
                   % (live_latest, repo_latest),
            object_schema="supabase_migrations", object_name="schema_migrations",
            metrics={"repo_latest": repo_latest, "live_latest": live_latest},
            evidence_kinds=("change_control",),
            remediation="capture the out-of-band DDL as a migration file in the repo so every schema "
                        "change is attributable to a reviewed, versioned migration"))
    else:
        out.append(C.make_finding(
            "schema_matches_repo", "schema_drift", "info",
            "live schema version matches the repo (%s, %s migrations)" % (repo_latest, live_count or len(repo_versions)),
            object_schema="supabase_migrations", object_name="schema_migrations",
            metrics={"latest": repo_latest, "count": live_count or len(repo_versions)},
            evidence_kinds=("change_control",), direction="supports",
            remediation=""))
    return out


def scan_source(source, tiers=None, dry_run=False, adapters=None, probes=None):
    """Run the due probes against one source and reconcile findings.

    Returns {"ok", "findings", "delta", "snapshot", "error", "duration_ms"}.
    `dry_run` runs the probes but writes nothing (the CLI uses it).
    """
    started = time.time()
    adapters = adapters or _import("db_adapters")
    probes = probes or _import("db_probes")
    if not adapters or not probes:
        return {"ok": False, "error": "db_adapters/db_probes unavailable", "findings": [], "delta": {}}
    caps = _capabilities(source, adapters)
    tiers = tuple(tiers or _due_tiers(source))
    try:
        result = probes.run_all(source, query_fn=adapters.query, tiers=tiers,
                                advisors_fn=getattr(adapters, "supabase_advisors", None),
                                capabilities=caps) or {}
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, str(e)[:200])
        if not dry_run:
            db_registry.record_scan(source["id"], ok=False, error=err)
        return {"ok": False, "error": err, "findings": [], "delta": {},
                "duration_ms": round((time.time() - started) * 1000)}
    findings = list(result.get("findings") or [])
    facts = dict(result.get("facts") or {})
    results = list(result.get("results") or [])
    try:
        findings.extend(_repo_migration_drift(source, facts))
    except Exception as e:
        print("db_steering: drift probe failed: %s" % str(e)[:120])
    ok_probes = {r.get("probe_id") for r in results if r.get("ok")}
    failed = [r for r in results if not r.get("ok")]
    all_failed = bool(results) and not ok_probes
    if dry_run:
        return {"ok": not all_failed, "findings": findings, "facts": facts, "results": results,
                "delta": {}, "duration_ms": round((time.time() - started) * 1000)}

    delta = reconcile_findings(source, findings, ok_probes)
    snapshot = write_snapshot(source, findings, results, facts, probes)
    for tier in tiers:
        caps.setdefault("tiers", {})[tier] = time.time()
    db_registry.record_scan(source["id"], ok=not all_failed,
                            error=("; ".join(str(f.get("error"))[:80] for f in failed[:3]) or None) if failed else None,
                            capabilities=caps)
    return {"ok": not all_failed, "findings": findings, "delta": delta, "snapshot": snapshot,
            "facts": facts, "results": results, "error": None,
            "duration_ms": round((time.time() - started) * 1000)}


def _import(name):
    try:
        return __import__(name)
    except Exception as e:
        print("db_steering: cannot import %s: %s: %s" % (name, type(e).__name__, str(e)[:120]))
        return None


# ── reconciliation ────────────────────────────────────────────────────────────────────

def _bulk_insert(table, rows):
    """Insert `rows` in chunks through one PostgREST POST each (an array body), falling
    back to per-row inserts for a chunk that fails so one bad row cannot lose a batch.
    Returns the persisted rows (with ids) in input order where the server echoed them."""
    out = []
    for i in range(0, len(rows), max(1, BULK_CHUNK)):
        chunk = rows[i:i + BULK_CHUNK]
        try:
            res = db._req("POST", "/rest/v1/%s" % table, body=chunk,
                          headers={"Prefer": "return=representation"})
            if isinstance(res, list) and len(res) == len(chunk):
                out.extend(res)
                continue
            raise RuntimeError("bulk insert echoed %s rows for %d" % (
                len(res) if isinstance(res, list) else type(res).__name__, len(chunk)))
        except Exception as e:
            print("db_steering: bulk insert of %d rows fell back to per-row: %s" % (len(chunk), str(e)[:120]))
            for rec in chunk:
                try:
                    res = db.insert(table, rec)
                    saved = res[0] if isinstance(res, list) and res else (res if isinstance(res, dict) else None)
                    out.append(saved if saved and saved.get("id") else rec)
                except Exception as e2:
                    print("db_steering: insert %s failed (%s): %s" % (table, rec.get("probe_id"), str(e2)[:120]))
    return out


def reconcile_findings(source, findings, ok_probes):
    """Upsert this cycle's findings and resolve the ones that disappeared.

    A finding is resolved ONLY when its probe ran successfully this cycle and did not
    report it again; a probe that errored says nothing about its findings. Returns
    {"new": [rows], "resolved": [rows], "updated": n, "all": [rows]} — rows carry ids so
    db_memo can attach evidence.
    """
    sid = source["id"]
    project = source.get("project")
    try:
        # Paged to exhaustion: PostgREST caps a single select at 1000 rows and a large
        # schema (tomorrow: 628 tables, apparently: 917) yields more findings than that. A
        # truncated read here would re-insert live rows and never resolve the tail.
        existing = db.select_all("db_findings", {"select": "*", "source_id": "eq.%s" % sid,
                                                 "status": "in.(open,acknowledged)"}, order="id.asc") or []
    except Exception as e:
        print("db_steering: cannot read existing findings: %s" % str(e)[:120])
        existing = []
    by_fp = {r.get("fingerprint"): r for r in existing}
    now = _now_iso()
    now_ts = time.time()
    new_rows, updated, seen, all_rows, pending = [], 0, set(), [], []
    for f in findings:
        fp = f.get("fingerprint")
        if not fp or fp in seen:
            continue
        seen.add(fp)
        row = by_fp.get(fp)
        if row:
            # WRITE ECONOMY: a finding that is exactly as it was is not re-written every
            # cycle. Its `last_seen_at` is touched at most once per FINDING_TOUCH_S; a
            # change in severity/detail/metrics is written immediately. The first live
            # scan showed why: 296 findings x 15 sources x 144 cycles/day of PATCHes
            # would have been the loop's dominant cost, for facts that had not moved.
            patch = {}
            for k in ("severity", "title", "detail", "metrics", "remediation", "direction"):
                if f.get(k) != row.get(k):
                    patch[k] = f.get(k)
            stale = now_ts - _ts(row.get("last_seen_at")) >= FINDING_TOUCH_S
            if patch or stale:
                patch.update({"last_seen_at": now, "occurrences": int(row.get("occurrences") or 0) + 1})
                try:
                    db.update("db_findings", {"id": row["id"]}, patch)
                    row.update(patch)
                    updated += 1
                except Exception as e:
                    print("db_steering: update finding failed: %s" % str(e)[:120])
            all_rows.append(row)
            continue
        pending.append({"source_id": sid, "project": project, "probe_id": f["probe_id"], "category": f["category"],
                        "severity": f["severity"], "fingerprint": fp, "title": f["title"], "detail": f.get("detail"),
                        "object_schema": f.get("object_schema"), "object_name": f.get("object_name"),
                        "metrics": f.get("metrics") or {}, "evidence_kinds": list(f.get("evidence_kinds") or []),
                        "direction": f.get("direction", "undermines"), "remediation": f.get("remediation"),
                        "status": "open", "first_seen_at": now, "last_seen_at": now, "occurrences": 1})
    for saved in _bulk_insert("db_findings", pending):
        new_rows.append(saved)
        all_rows.append(saved)
    resolved = []
    for fp, row in by_fp.items():
        if fp in seen or row.get("probe_id") not in ok_probes:
            continue
        try:
            db.update("db_findings", {"id": row["id"]}, {"status": "resolved", "resolved_at": now, "last_seen_at": row.get("last_seen_at")})
            row["status"] = "resolved"
            row["resolved_at"] = now
            resolved.append(row)
        except Exception as e:
            print("db_steering: resolve finding failed: %s" % str(e)[:120])
    return {"new": new_rows, "resolved": resolved, "updated": updated, "all": all_rows}


def write_snapshot(source, findings, results, facts, probes=None):
    counts = {"by_severity": {}, "by_category": {}, "supports": 0, "undermines": 0}
    for f in findings:
        if f.get("direction") == "supports":
            counts["supports"] += 1
            continue
        counts["undermines"] += 1
        counts["by_severity"][f["severity"]] = counts["by_severity"].get(f["severity"], 0) + 1
        counts["by_category"][f["category"]] = counts["by_category"].get(f["category"], 0) + 1
    try:
        score = float(probes.score(findings)) if probes else None
    except Exception as e:
        print("db_steering: score failed: %s" % str(e)[:80])
        score = None
    stats = {"probes_run": len(results), "probes_ok": sum(1 for r in results if r.get("ok")),
             "probes_failed": [r.get("probe_id") for r in results if not r.get("ok")][:20],
             "duration_ms": sum(float(r.get("duration_ms") or 0) for r in results)}
    summary = ""
    try:
        summary = probes.summarize(findings, limit=8) if probes else ""
    except Exception as e:
        print("db_steering: summarize failed: %s" % str(e)[:80])
    snap = {"source_id": source["id"], "project": source.get("project"), "taken_at": _now_iso(),
            "score": score, "counts": counts, "probe_stats": stats, "facts": C._jsonable(facts),
            "summary": (summary or "")[:4000]}
    try:
        db.insert("db_posture_snapshots", snap)
    except Exception as e:
        print("db_steering: snapshot insert failed: %s" % str(e)[:120])
    return snap


# ── steering brief (what the coder agents read) ───────────────────────────────────────

def _open_findings(project, limit=200):
    """Open undermining findings for the brief, most severe first.

    Severity is walked one tier at a time (critical, high, medium, low) so a project with
    thousands of low findings can never crowd a critical one out of the window; each tier
    is a deterministic window of `limit` rows, newest first."""
    out = []
    try:
        for sev in reversed(C.SEVERITIES):
            rows = db.select("db_findings", {
                "select": "id,probe_id,category,severity,title,detail,object_schema,object_name,remediation,direction,first_seen_at,last_seen_at,occurrences,status",
                "project": "eq.%s" % project, "status": "in.(open,acknowledged)", "direction": "eq.undermines",
                "severity": "eq.%s" % sev, "order": "last_seen_at.desc,id.asc", "limit": str(limit)}) or []
            out.extend(rows)
        return out
    except Exception as e:
        print("db_steering: open findings read failed: %s" % str(e)[:120])
        return []


def build_brief(project, findings=None, signals=None):
    """Compose the <=BRIEF_MAX_CHARS brief for one project. Deterministic; no model.

    Order: memo steering signals first (they are the argument-level view), then the most
    severe open gaps grouped by probe with the concrete objects and the remediation.
    """
    findings = findings if findings is not None else _open_findings(project)
    findings = [f for f in findings if f.get("direction", "undermines") == "undermines"]
    findings.sort(key=lambda f: (-C.SEVERITY_RANK.get(f.get("severity"), 0), f.get("probe_id") or ""))
    if not findings and not signals:
        return "", {}
    counts = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    lines = ["## Database steering (live findings for %s — apply when your change touches these objects)" % project]
    if counts:
        lines.append("Open gaps: " + ", ".join("%d %s" % (counts[s], s) for s in reversed(C.SEVERITIES) if counts.get(s)))
    for s in (signals or [])[:6]:
        lines.append("- " + str(s).strip())
    groups = {}
    for f in findings:
        groups.setdefault(f.get("probe_id"), []).append(f)
    for pid, fs in groups.items():
        if C.SEVERITY_RANK.get(fs[0].get("severity"), 0) < C.SEVERITY_RANK["medium"]:
            continue
        objs = sorted({("%s.%s" % (f.get("object_schema") or "public", f.get("object_name"))).strip(".")
                       for f in fs if f.get("object_name")})
        head = "- [%s] %s" % (fs[0]["severity"].upper(), fs[0]["title"] if len(fs) == 1 else
                              "%s (%d objects)" % (pid.replace("_", " "), len(fs)))
        if objs:
            head += ": " + ", ".join(objs[:8]) + (" …" if len(objs) > 8 else "")
        rem = (fs[0].get("remediation") or "").strip()
        if rem:
            head += " -> " + rem[:220]
        lines.append(head)
    lines.append("Rule: never enable RLS without policies, never drop or rename a column in the same "
                 "release that stops writing it, add created_at timestamptz default now() to every new table.")
    text = "\n".join(lines)
    if len(text) > BRIEF_MAX_CHARS:
        text = text[:BRIEF_MAX_CHARS - 2].rsplit("\n", 1)[0] + "\n…"
    return text + "\n\n", counts


def refresh_brief(project, signals=None):
    """Write db_steering_briefs when the content changed. Returns the brief text."""
    text, counts = build_brief(project, signals=signals)
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
    try:
        cur = db.select("db_steering_briefs", {"select": "findings_hash", "project": "eq.%s" % project, "limit": "1"}) or []
        if cur and cur[0].get("findings_hash") == h:
            return text
        if not text:
            if cur:
                db.delete("db_steering_briefs", {"project": project})
            return ""
        db.upsert("db_steering_briefs", {"project": project, "brief": text, "findings_hash": h,
                                         "open_counts": counts, "updated_at": _now_iso()})
    except Exception as e:
        print("db_steering: brief write failed for %s: %s" % (project, str(e)[:120]))
    _brief_cache.pop(project, None)
    return text


def steering_brief(project):
    """Read side used by prompt_assembler: cached, fail-soft, '' when there is none."""
    if not project:
        return ""
    hit = _brief_cache.get(project)
    if hit and time.time() - hit[0] < BRIEF_CACHE_TTL_S:
        return hit[1]
    text = ""
    try:
        rows = db.select("db_steering_briefs", {"select": "brief", "project": "eq.%s" % project, "limit": "1"}) or []
        text = (rows[0].get("brief") or "") if rows else ""
    except Exception:
        text = ""
    _brief_cache[project] = (time.time(), text)
    return text


# ── remediation through the swarm filer ──────────────────────────────────────────────

def _slug(probe_id, project):
    base = re.sub(r"[^a-z0-9]+", "-", ("swarm-db-%s-%s" % (probe_id, project)).lower()).strip("-")
    return base[:80]


def _unfiled_open(project, limit=UNFILED_RETRY_LIMIT):
    """Open, material, undermining findings of `project` that carry no task_slug yet.

    Remediation is filed from the scan delta, so a finding that was first persisted by a
    manual scan, or whose enqueue was refused (release backpressure, a paused project),
    would otherwise stay unfiled forever. swarm_enqueue dedupes on the open intent key, so
    re-offering these is idempotent. Fail-soft: [] on any read error."""
    if not project:
        return []
    try:
        return db.select("db_findings", {
            "select": "id,probe_id,category,severity,title,detail,object_schema,object_name,remediation,direction,fingerprint,status,task_slug",
            "project": "eq.%s" % project, "status": "in.(open,acknowledged)", "direction": "eq.undermines",
            "severity": "in.(high,critical)", "task_slug": "is.null",
            "order": "last_seen_at.desc,id.asc", "limit": str(limit)}) or []
    except Exception as e:
        print("db_steering: unfiled findings read failed for %s: %s" % (project, str(e)[:120]))
        return []


def file_remediation(source, new_rows, budget=MAX_TASKS_PER_RUN):
    """One swarm task per (project, probe) for material NEW gaps. Returns slugs filed."""
    if not REMEDIATION_ENABLED or budget <= 0:
        return []
    project = source.get("project")
    if not project or (source.get("config") or {}).get("self"):
        return []
    material = [r for r in new_rows if C.is_material(r) and r.get("direction", "undermines") == "undermines"]
    if not material:
        return []
    try:
        proj = (db.select("projects", {"select": "id,repo_path,superseded_by", "name": "eq.%s" % project, "limit": "1"}) or [{}])[0]
    except Exception:
        proj = {}
    if not proj.get("id") or proj.get("superseded_by") or not proj.get("repo_path"):
        return []
    try:
        import swarm_enqueue
    except Exception as e:
        print("db_steering: swarm_enqueue unavailable: %s" % str(e)[:80])
        return []
    groups = {}
    for r in material:
        groups.setdefault(r.get("probe_id"), []).append(r)
    filed = []
    for pid, rows in sorted(groups.items(), key=lambda kv: -C.SEVERITY_RANK.get(kv[1][0].get("severity"), 0)):
        if len(filed) >= budget:
            break
        slug = _slug(pid, project)
        objs = sorted({"%s.%s" % (r.get("object_schema") or "public", r.get("object_name")) for r in rows if r.get("object_name")})
        prompt = (
            "DATABASE STEERING (auto-filed from a read-only review of the %s production database; "
            "severity %s).\n\nFinding: %s\n%s\nObjects: %s\n\nRemediation: %s\n\n"
            "Deliver as a versioned migration under supabase/migrations (or the project's migration "
            "dir) plus the code change it needs, with tests. Do not apply DDL directly to production. "
            "Never enable RLS without policies. Keep the diff minimal and reversible. "
            "Fingerprints: %s" % (
                project, rows[0].get("severity"), rows[0].get("title"), (rows[0].get("detail") or "")[:600],
                ", ".join(objs[:25]) or "n/a", (rows[0].get("remediation") or "")[:800],
                ", ".join((r.get("fingerprint") or "")[:12] for r in rows[:12])))
        try:
            res = swarm_enqueue.enqueue({"project_id": proj["id"], "slug": slug, "kind": "bugfix",
                                         "prompt": prompt, "note": "db_steering %s" % pid})
            filed.append(slug)
            for r in rows:
                if r.get("id"):
                    try:
                        db.update("db_findings", {"id": r["id"]}, {"task_slug": slug})
                    except Exception as e:
                        print("db_steering: task_slug write failed for %s: %s" % (r.get("id"), str(e)[:80]))
            print("db_steering: filed %s (%s)" % (slug, getattr(res, "status", res)))
        except Exception as e:
            print("db_steering: enqueue %s failed: %s: %s" % (slug, type(e).__name__, str(e)[:120]))
    return filed


# ── the loop ──────────────────────────────────────────────────────────────────────────

def run(budget_s=None, sources=None, dry_run=False, project=None):
    """One cycle. Called by loops.py (type 'db_steering') and by the CLI."""
    started = time.time()
    budget_s = float(budget_s if budget_s is not None else BUDGET_S)
    out = {"sources": 0, "scanned": 0, "skipped_budget": 0, "failed": 0, "new": 0, "resolved": 0,
           "tasks": [], "memos": 0, "discovery": None, "posture_backfill": 0}
    if not dry_run:
        ensure_loop_row()
        out["discovery"] = db_registry.discover()
        out["posture_backfill"] = db_registry.sync_security_posture()
    memo = _import("db_memo")
    rows = sources if sources is not None else db_registry.list_sources(enabled_only=True, project=project)
    # Stalest first: a source that keeps missing the budget window rises to the top.
    rows = sorted(rows, key=lambda s: _ts(s.get("last_scan_at")))
    out["sources"] = len(rows)
    touched_projects = set()
    tasks_budget = MAX_TASKS_PER_RUN
    for s in rows:
        if time.time() - started > budget_s:
            out["skipped_budget"] += 1
            continue
        res = scan_source(s, dry_run=dry_run)
        out["scanned"] += 1
        if not res.get("ok"):
            out["failed"] += 1
        if dry_run:
            continue
        delta = res.get("delta") or {}
        out["new"] += len(delta.get("new") or [])
        out["resolved"] += len(delta.get("resolved") or [])
        candidates = list(delta.get("new") or [])
        if tasks_budget > 0 and REMEDIATION_ENABLED:
            seen = {r.get("id") for r in candidates if r.get("id")}
            candidates += [r for r in _unfiled_open(s.get("project")) if r.get("id") not in seen]
        filed = file_remediation(s, candidates, budget=tasks_budget)
        tasks_budget -= len(filed)
        out["tasks"].extend(filed)
        proj = s.get("project")
        if proj:
            touched_projects.add(proj)
            if memo:
                try:
                    memo.attach_evidence(proj, (delta.get("all") or []) + (delta.get("resolved") or []))
                except Exception as e:
                    print("db_steering: memo attach failed for %s: %s" % (proj, str(e)[:120]))
    if dry_run:
        out["duration_s"] = round(time.time() - started, 1)
        return out
    memo_started = time.time()
    for proj in sorted(touched_projects):
        signals = []
        if memo:
            try:
                if time.time() - memo_started <= MEMO_BUDGET_S:
                    r = memo.rebuild_if_changed(proj) or {}
                    out["memos"] += int(r.get("drafted") or 0) + int(r.get("deterministic") or 0)
                else:
                    # Evidence is already attached; the draft catches up next cycle. The
                    # signals and the brief never wait on a model.
                    out["memos_deferred"] = out.get("memos_deferred", 0) + 1
                signals = memo.steering_signals(proj) or []
            except Exception as e:
                print("db_steering: memo rebuild failed for %s: %s" % (proj, str(e)[:120]))
        refresh_brief(proj, signals=signals)
    out["duration_s"] = round(time.time() - started, 1)
    print("db_steering: " + json.dumps(out, default=str))
    return out


if __name__ == "__main__":
    import single_instance
    _owned, _deadline = single_instance.guard("db_steering", interval_s=LOOP_CADENCE_S)
    if not _owned:
        print(json.dumps({"skipped": "db_steering already running"}))
        raise SystemExit(0)
    try:
        print(json.dumps(run(project=(sys.argv[1] if len(sys.argv) > 1 else None)), indent=2, default=str))
    finally:
        if _deadline is not None:
            _deadline.cancel()
