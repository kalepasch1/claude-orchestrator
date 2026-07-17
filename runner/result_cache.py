#!/usr/bin/env python3
"""
result_cache.py - semantic-ish result cache. Identical/near-identical tasks (same repo,
same normalized prompt, same base commit) reuse the prior result instead of paying for a
fresh run. Stored in Supabase `result_cache`.
"""
import os, sys, hashlib, re, subprocess, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def _norm(prompt):
    return re.sub(r"\s+", " ", (prompt or "").strip().lower())


def signature(project, prompt, repo, base="main"):
    try:
        commit = subprocess.check_output(["git", "rev-parse", base], cwd=repo, text=True).strip()
    except Exception:
        commit = base
    raw = f"{project}|{commit}|{_norm(prompt)}"
    return hashlib.sha256(raw.encode()).hexdigest()


def lookup(sig):
    try:
        rows = db.select("result_cache", {"select": "*", "signature": f"eq.{sig}"}) or []
        if rows:
            db.update("result_cache", {"signature": sig},
                      {"hits": (rows[0].get("hits", 0) or 0) + 1,
                       "last_used": datetime.datetime.utcnow().isoformat()})
            return rows[0]
    except Exception:
        pass
    return None


def store(sig, project, slug, branch, summary):
    try:
        db.insert("result_cache", {"signature": sig, "project": project, "slug": slug,
                                   "branch": branch, "summary": summary[:1000]}, upsert=True)
    except Exception:
        pass


def invalidate(sig):
    """Remove a cached result by signature."""
    try:
        db.delete("result_cache", {"signature": f"eq.{sig}"})
        return True
    except Exception:
        return False


def stats():
    """Return cache statistics for operator observability."""
    try:
        rows = db.select("result_cache", {"select": "*", "limit": "10000"}) or []
    except Exception:
        rows = []
    projects = {}
    total_hits = 0
    for r in rows:
        p = r.get("project") or "unknown"
        projects[p] = projects.get(p, 0) + 1
        total_hits += r.get("hits", 0) or 0
    return {
        "total_entries": len(rows),
        "total_hits": total_hits,
        "by_project": projects,
    }
