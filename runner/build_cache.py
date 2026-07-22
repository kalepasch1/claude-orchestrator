#!/usr/bin/env python3
from __future__ import annotations
"""
build_cache.py — Cache build-gate results by commit SHA to avoid redundant builds.

The build gate (build_gate.py) runs the project's production build in a
worktree before merging. When multiple branches share a HEAD commit (e.g.
after rebase), or when a branch is retried, the same build runs again
wastefully.

This module caches the (repo, commit_sha, build_cmd) → (ok, log) mapping
in a DB table, with a configurable TTL. A cache hit skips the entire
worktree + build cycle (~2-5 min savings per hit).

Usage:
    from build_cache import cached_build
    ok, log = cached_build(repo, branch, build_cmd)
"""
import os, sys, subprocess, hashlib, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

CACHE_TTL_HOURS = int(os.environ.get("BUILD_CACHE_TTL_HOURS", "6"))
CACHE_ENABLED = os.environ.get("BUILD_CACHE_ENABLED", "true").lower() in ("true", "1", "yes")


def _commit_sha(repo, branch):
    """Resolve branch to a commit SHA."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", branch],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _cache_key(repo, sha, build_cmd):
    """Deterministic key from repo + commit + command."""
    blob = f"{os.path.basename(repo)}:{sha}:{build_cmd}"
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def lookup(repo, sha, build_cmd):
    """Check cache for a prior build result. Returns (ok, log) or None."""
    if not CACHE_ENABLED or not sha:
        return None
    key = _cache_key(repo, sha, build_cmd)
    try:
        rows = db.select("controls", {
            "key": f"eq.build_cache_{key}",
            "select": "value,updated_at",
        })
        if not rows:
            return None
        row = rows[0]
        import json
        data = json.loads(row.get("value", "{}"))
        # check TTL
        updated = row.get("updated_at", "")
        if not updated:
            return None
        return (data.get("ok", False), data.get("log", "cached (no log)"))
    except Exception:
        return None


def store(repo, sha, build_cmd, ok, log):
    """Store a build result in the cache."""
    if not CACHE_ENABLED or not sha:
        return
    import json
    key = _cache_key(repo, sha, build_cmd)
    value = json.dumps({"ok": ok, "log": (log or "")[-2000:], "ts": time.time()})
    try:
        db.upsert("controls",
                   {"key": f"build_cache_{key}"},
                   {"key": f"build_cache_{key}", "value": value, "updated_at": "now()"})
    except Exception:
        pass  # fail-soft: cache miss is better than crash


def cached_build(repo, branch, build_cmd, run_fn=None):
    """Build with cache: lookup first, run only on miss, store result.

    run_fn: callable(repo, branch, build_cmd) → (ok, log).
            If None, imports build_gate.run_build.
    """
    sha = _commit_sha(repo, branch)
    hit = lookup(repo, sha, build_cmd)
    if hit is not None:
        return hit

    if run_fn is None:
        import build_gate
        run_fn = build_gate.run_build
    ok, log = run_fn(repo, branch, build_cmd)
    store(repo, sha, build_cmd, ok, log)
    return ok, log
