"""Fleet baselines: where one project's data posture sits against every linked database.

A finding says "this table has no RLS". A baseline says "this project carries 14 open
security gaps where the fleet median is 6 — worst quartile". The second sentence is what
a memo argument or a coder brief can lean on: it turns an absolute observation into a
comparative one, which is how reasonableness is actually argued (industry practice, peer
posture) and how an agent decides which of many gaps to fix first.

Everything here reads the latest db_posture_snapshots per source and aggregates per
project. No model calls, no writes, fail-soft, cached for CACHE_TTL_S per process.
"""
from __future__ import annotations

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402

CACHE_TTL_S = int(os.environ.get("ORCH_DB_BASELINE_TTL_S", "300"))
SNAPSHOT_WINDOW = int(os.environ.get("ORCH_DB_BASELINE_SNAPSHOTS", "600"))
MIN_PROJECTS = 3  # below this a "fleet median" is not a meaningful comparison
_cache = {"at": 0.0, "value": None}


def _latest_per_source(limit=SNAPSHOT_WINDOW) -> list:
    """Newest snapshot for every source. The window is ordered newest-first; with
    snapshots written only when the posture moves (or hourly) it spans days."""
    rows = db.select("db_posture_snapshots", {
        "select": "source_id,project,taken_at,score,counts",
        "order": "taken_at.desc,id.asc", "limit": str(limit)}) or []
    seen, out = set(), []
    for r in rows:
        sid = r.get("source_id")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append(r)
    return out


def _per_project(snaps: list) -> dict:
    """{project: {"score": min score across its sources, "sources": n,
                  "by_category": {cat: n}, "by_severity": {sev: n}, "undermines": n}}"""
    agg = {}
    for s in snaps:
        proj = s.get("project")
        if not proj:
            continue
        cur = agg.setdefault(proj, {"score": None, "sources": 0, "by_category": {}, "by_severity": {}, "undermines": 0})
        cur["sources"] += 1
        try:
            sc = float(s.get("score")) if s.get("score") is not None else None
        except (TypeError, ValueError):
            sc = None
        if sc is not None:
            cur["score"] = sc if cur["score"] is None else min(cur["score"], sc)
        counts = s.get("counts") or {}
        for cat, n in (counts.get("by_category") or {}).items():
            cur["by_category"][cat] = cur["by_category"].get(cat, 0) + int(n or 0)
        for sev, n in (counts.get("by_severity") or {}).items():
            cur["by_severity"][sev] = cur["by_severity"].get(sev, 0) + int(n or 0)
        cur["undermines"] += int(counts.get("undermines") or 0)
    return agg


def fleet() -> dict:
    """The whole-fleet view, cached. {"projects": {...}, "n": n, "median_score": x,
    "median_by_category": {cat: median}, "computed_at": ts}. Never raises."""
    now = time.time()
    if _cache["value"] is not None and now - _cache["at"] < CACHE_TTL_S:
        return _cache["value"]
    out = {"projects": {}, "n": 0, "median_score": None, "median_by_category": {}, "computed_at": now}
    try:
        projects = _per_project(_latest_per_source())
        out["projects"] = projects
        out["n"] = len(projects)
        scores = [p["score"] for p in projects.values() if p["score"] is not None]
        if scores:
            out["median_score"] = round(statistics.median(scores), 1)
        cats = {c for p in projects.values() for c in p["by_category"]}
        for c in sorted(cats):
            vals = [p["by_category"].get(c, 0) for p in projects.values()]
            out["median_by_category"][c] = statistics.median(vals) if vals else 0
    except Exception as e:
        print(f"db_baselines: fleet() failed: {type(e).__name__}: {str(e)[:120]}")
    _cache["at"], _cache["value"] = now, out
    return out


def baseline(project: str) -> dict:
    """One project against the fleet. {} when the fleet is too small or the project is
    unknown. Keys: score, rank (1 = healthiest), n, median_score, categories: [{category,
    count, median, ratio, quartile}] sorted worst-first."""
    if not project:
        return {}
    f = fleet()
    projects = f.get("projects") or {}
    me = projects.get(project)
    if not me or f.get("n", 0) < MIN_PROJECTS:
        return {}
    scored = sorted(((p["score"], name) for name, p in projects.items() if p["score"] is not None), reverse=True)
    rank = next((i + 1 for i, (_, name) in enumerate(scored) if name == project), None)
    cats = []
    for cat, n in me["by_category"].items():
        med = float(f["median_by_category"].get(cat, 0) or 0)
        vals = sorted(p["by_category"].get(cat, 0) for p in projects.values())
        worse_than = sum(1 for v in vals if v < n)
        pct = worse_than / max(1, len(vals))
        quartile = "worst" if pct >= 0.75 else ("below-median" if pct >= 0.5 else ("median" if pct >= 0.25 else "best"))
        cats.append({"category": cat, "count": n, "median": med,
                     "ratio": (round(n / med, 2) if med else None), "quartile": quartile})
    cats.sort(key=lambda c: (-(c["ratio"] or (99 if c["count"] else 0)), -c["count"]))
    return {"project": project, "score": me["score"], "rank": rank, "n": len(scored) or f["n"],
            "median_score": f.get("median_score"), "sources": me["sources"], "categories": cats}


def baseline_lines(project: str, max_categories: int = 3) -> list:
    """Two or three plain sentences for a brief or a memo prompt; [] when no baseline."""
    b = baseline(project)
    if not b:
        return []
    lines = []
    if b.get("score") is not None and b.get("rank"):
        lines.append("Fleet baseline: posture %d/100, rank %d of %d linked projects (fleet median %s)." % (
            round(b["score"]), b["rank"], b["n"], b.get("median_score")))
    worst = [c for c in b["categories"] if c["quartile"] in ("worst", "below-median") and c["count"] > 0]
    for c in worst[:max_categories]:
        lines.append("%s gaps: %d vs fleet median %g — %s quartile." % (
            c["category"], c["count"], c["median"], c["quartile"]))
    best = [c for c in b["categories"] if c["quartile"] == "best" and c["median"] > 0]
    if best and len(lines) < max_categories + 1:
        lines.append("At or better than the fleet on: %s." % ", ".join(c["category"] for c in best[:4]))
    return lines


def reset_cache():
    _cache["at"], _cache["value"] = 0.0, None
