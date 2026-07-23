#!/usr/bin/env python3
"""
result_cache.py - semantic-ish result cache. Identical/near-identical tasks (same repo,
same normalized prompt, same base commit) reuse the prior result instead of paying for a
fresh run. Stored in Supabase `result_cache`.
"""
import os, sys, hashlib, re, subprocess, datetime, typing
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def _norm(prompt: typing.Optional[str]) -> str:
    """Collapse whitespace and lowercase for prompt dedup comparison."""
    return re.sub(r"\s+", " ", (prompt or "").strip().lower())


def signature(project: str, prompt: str, repo: str, base: str = "main",
              design_fingerprint: str = "") -> str:
    """SHA-256 cache key from project, base, prompt, and Markdown design corpus."""
    try:
        commit = subprocess.check_output(["git", "rev-parse", base], cwd=repo, text=True).strip()
    except Exception:
        commit = base
    raw = f"{project}|{commit}|{_norm(prompt)}|{design_fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()


def lookup(sig: str) -> typing.Optional[dict]:
    """Return cached result row if present; bump hit counter. None on miss."""
    try:
        rows = db.select("result_cache", {"select": "*", "signature": f"eq.{sig}"}) or []
        if rows:
            db.update("result_cache", {"signature": sig},
                      {"hits": (rows[0].get("hits", 0) or 0) + 1,
                       "last_used": datetime.datetime.now(datetime.timezone.utc).isoformat()})
            return rows[0]
    except Exception:
        pass
    return None


def store(sig: str, project: str, slug: str, branch: str, summary: str) -> None:
    """Upsert a cache entry (truncates summary to 1000 chars)."""
    try:
        db.insert("result_cache", {"signature": sig, "project": project, "slug": slug,
                                   "branch": branch, "summary": summary[:1000]}, upsert=True)
    except Exception:
        pass


def invalidate(sig=None, project=None):
    """Remove cache entries by signature or project. Useful after schema changes or
    force-rebuilds where stale cached results would cause silent regressions."""
    try:
        if sig:
            db.delete("result_cache", {"signature": f"eq.{sig}"})
        elif project:
            db.delete("result_cache", {"project": f"eq.{project}"})
    except Exception:
        pass


def stats():
    """Return cache size and total hits for diagnostics."""
    try:
        rows = db.select("result_cache", {"select": "signature,hits"}) or []
        return {"entries": len(rows), "total_hits": sum(r.get("hits", 0) or 0 for r in rows)}
    except Exception:
        return {"entries": 0, "total_hits": 0}
