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
    """Normalize a prompt string for cache-key comparison.

    Strips leading/trailing whitespace, lowercases, and collapses all
    internal whitespace runs to a single space so that cosmetically
    different prompts that carry the same semantic intent produce the
    same cache signature.
    """
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
