#!/usr/bin/env python3
from __future__ import annotations
"""
precedent.py - retrieval-augmented drafting. Before an agent writes a change from scratch, find the
most-similar change that ALREADY MERGED and hand it to the drafter as a worked example. Turns "invent a
solution" into "adapt a known-good pattern" — the single biggest quality/yield multiplier, and it costs
no model tokens (pure retrieval from our own merge history + git).

Lightweight by design (no embeddings dependency): token-overlap match on prior merged task prompts, then
pull that change's diff from git. Fail-soft: returns '' on any problem so it can never block drafting.
"""
import os, sys, re, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("the a an and or to of in for on with is are be this that it as at by from make add fix "
            "update create implement use using into your our task app code file files change".split())


def _tokens(s):
    return {w for w in _WORD.findall((s or "").lower()) if len(w) > 2 and w not in _STOP}


def _merged_diff(repo, slug, max_bytes=8000):
    """Best-effort diff of a prior merged change, by slug, from git history."""
    try:
        # the merge/train commits reference the branch name agent/<slug>
        sha = subprocess.run(["git", "-C", repo, "log", "--all", "--format=%H",
                              f"--grep=agent/{slug}", "--max-count=1"],
                             capture_output=True, text=True, timeout=15).stdout.strip().split("\n")[0]
        if not sha:
            r = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", f"agent/{slug}"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                sha = r.stdout.strip()
        if not sha:
            return ""
        diff = subprocess.run(["git", "-C", repo, "show", "--stat", "-p", sha],
                              capture_output=True, text=True, timeout=20).stdout
        return diff[:max_bytes]
    except Exception:
        return ""


def hint(task, repo, project_id=None):
    """Return an injectable 'adapt this proven change' block, or '' if no good precedent."""
    if os.environ.get("ORCH_PRECEDENT", "true").lower() not in ("true", "1", "yes"):
        return ""
    if not repo or not os.path.isdir(repo):
        return ""
    want = _tokens(f"{task.get('slug','')} {task.get('prompt','')}")
    if len(want) < 3:
        return ""
    try:
        q = {"select": "slug,prompt,project_id", "state": "eq.MERGED",
             "order": "updated_at.desc", "limit": "200"}
        if project_id:
            q["project_id"] = f"eq.{project_id}"
        rows = db.select("tasks", q) or []
    except Exception:
        return ""
    best, best_score = None, 0.0
    for r in rows:
        if r.get("slug") == task.get("slug"):
            continue
        have = _tokens(f"{r.get('slug','')} {r.get('prompt','')}")
        if not have:
            continue
        score = len(want & have) / len(want | have)  # Jaccard
        if score > best_score:
            best, best_score = r, score
    if not best or best_score < 0.12:
        return ""
    diff = _merged_diff(repo, best["slug"])
    if not diff:
        return ""
    return ("\n\n---\nPROVEN PRECEDENT — a similar change already shipped in this codebase "
            f"('{best['slug']}'). ADAPT this known-good pattern (files touched, structure, conventions) "
            "instead of inventing from scratch; do not copy blindly:\n```diff\n" + diff + "\n```")


if __name__ == "__main__":
    import json
    print(json.dumps({"tokens": list(_tokens("add stripe webhook handler"))[:8]}))
