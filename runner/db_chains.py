#!/usr/bin/env python3
"""db_chains.py — findings are rows; arguments are chains.

Two chain builders, both deterministic and read-only over state the loop already writes:

1. BLAST RADIUS. The fk_graph_edges probe stores FK edges in each snapshot's facts. A grant
   on table T is not a grant on one table — its blast radius walks the FK graph both ways
   (who references T, what T references). chain_lines() puts "opens into N tables" on the
   highest-signal grant/RLS findings so the brief argues reach, not row counts.
2. CROSS-PROJECT CORRELATION. db_baselines already ranks every project per category. When a
   project is worst-quartile on a failure class that a best peer closes at ZERO open
   findings, the actionable insight is "copy the peer's pattern", and its name is evidence in
   a memo (industry practice is provably achievable inside your own fleet).

No model calls, no writes; every function fail-soft, cached for CACHE_TTL_S per process.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402

SNAPSHOTS = "db_posture_snapshots"
FINDINGS = "db_findings"
CACHE_TTL_S = int(os.environ.get("ORCH_DB_CHAINS_TTL_S", "600"))
MAX_HOPS = 3
_facts_cache = {}


# ── blast radius over the FK graph ────────────────────────────────────────────────────

def _edges(project):
    """Latest snapshot's fk_edges for the project; [] when none yet. Cached briefly."""
    key = str(project or "")
    hit = _facts_cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL_S:
        return hit[1]
    edges = []
    try:
        rows = db.select(SNAPSHOTS, {"select": "facts", "project": "eq.%s" % key,
                                     "order": "taken_at.desc,id.desc", "limit": "1"}) or []
        facts = (rows[0].get("facts") or {}) if rows else {}
        edges = [e for e in (facts.get("fk_edges") or []) if isinstance(e, dict)]
    except Exception as e:
        print("db_chains: edges read failed for %s: %s" % (key, str(e)[:120]))
    _facts_cache[key] = (time.time(), edges)
    return edges


def blast_radius(project, table):
    """{ancestors: [...], descendants: [...], reach: n} — tables reachable from `table`
    through FK edges in either direction within MAX_HOPS. Deterministic; []-safe."""
    edges = _edges(project)
    if not edges or not table:
        return {"ancestors": [], "descendants": [], "reach": 0}
    child_to_parents = {}
    parent_to_children = {}
    for e in edges:
        c, p = e.get("child"), e.get("parent")
        if not c or not p:
            continue
        child_to_parents.setdefault(c, set()).add(p)
        parent_to_children.setdefault(p, set()).add(c)
    up, down, seen_up, seen_down = set(), set(), {table}, {table}
    frontier_up, frontier_down = [table], [table]
    for _ in range(MAX_HOPS):
        nxt_up = [p for t in frontier_up for p in child_to_parents.get(t, ()) if p not in seen_up]
        seen_up.update(nxt_up); up.update(nxt_up); frontier_up = nxt_up
        nxt_dn = [c for t in frontier_down for c in parent_to_children.get(t, ()) if c not in seen_down]
        seen_down.update(nxt_dn); down.update(nxt_dn); frontier_down = nxt_dn
    up.discard(table); down.discard(table)
    return {"ancestors": sorted(up), "descendants": sorted(down), "reach": len(up) + len(down)}


def chain_lines(project, limit=2):
    """Brief fragments naming reach for the worst open security/table findings."""
    try:
        rows = db.select(FINDINGS, {
            "select": "severity,title,object_name,probe_id", "project": "eq.%s" % project,
            "status": "eq.open", "direction": "eq.undermines",
            "severity": "in.(critical,high)",
            "order": "severity.desc,last_seen_at.desc", "limit": "20"}) or []
    except Exception as e:
        print("db_chains: findings read failed for %s: %s" % (project, str(e)[:120]))
        return []
    out = []
    for f in rows:
        obj = str(f.get("object_name") or "")
        if not obj:
            continue
        r = blast_radius(project, obj)
        if r["reach"] < 2:
            continue
        out.append("Chain: %s on public.%s — opens into %d tables via the FK graph (%s)"
                   % (f.get("probe_id", "").replace("_", " "), obj, r["reach"],
                      ", ".join((r["ancestors"] + r["descendants"])[:4])))
        if len(out) >= max(0, limit):
            break
    return out


# ── cross-project correlation ─────────────────────────────────────────────────────────

def peer_copy_lines(project, limit=1):
    """'worst-quartile on <category>; peer <best project> closes it at 0' — per fleet
    baseline categories. [] when the fleet is too small to compare (db_baselines rule)."""
    try:
        import db_baselines
        base = db_baselines.baseline(project) or {}
        fleet = db_baselines.fleet() or {}
    except Exception as e:
        print("db_chains: baseline read failed for %s: %s" % (project, str(e)[:120]))
        return []
    if not base or base.get("quartile") != "worst" and not any(
            c.get("quartile") == "worst" for c in (base.get("categories") or [])):
        return []
    projects = fleet.get("projects") or {}
    medians = fleet.get("median_by_category") or {}
    out = []
    for c in (base.get("categories") or []):
        if c.get("quartile") != "worst":
            continue
        cat = c.get("category")
        best = None
        for name, row in projects.items():
            if name == project:
                continue
            n = (row.get("by_category") or {}).get(cat, 0)
            if best is None or n < best[1]:
                best = (name, n)
        if best and best[1] == 0 and int(c.get("count") or 0) >= 3:
            out.append("Fleet: worst-quartile on %s (%s vs median %s) — %s closes this class at 0; copy its pattern"
                       % (cat, c.get("count"), medians.get(cat, "?"), best[0]))
        if len(out) >= max(0, limit):
            break
    return out
