#!/usr/bin/env python3
"""
context_cache_distill.py - periodic job wrapper around context_embed.distill().

.orch-context-cache.json (one per repo) never evicted old "filepath:mtime" entries — every
edit to a file left its previous vector in the cache forever. The orchestrator repo edits
itself constantly (self-improvement loop), so its own cache reached 877 entries / 14MB before
this existed. distill() prunes superseded mtime versions and caps total size; this job just
runs it across every known repo, including the orchestrator's own.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, context_embed

ORCH_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run():
    repos = {ORCH_REPO}
    try:
        for p in (db.select("projects", {"select": "repo_path"}) or []):
            rp = p.get("repo_path")
            if rp:
                repos.add(rp)
    except Exception as e:
        print(f"context_cache_distill: projects lookup failed ({e}); distilling orchestrator repo only")

    results = {}
    for repo in repos:
        if not os.path.isfile(os.path.join(repo, context_embed.CACHE_FILE)):
            continue
        try:
            results[repo] = context_embed.distill(repo)
        except Exception as e:
            results[repo] = {"error": str(e)}

    total_dropped = sum(r.get("dropped_stale", 0) + r.get("dropped_capacity", 0)
                        for r in results.values() if isinstance(r, dict))
    print(f"context_cache_distill: {len(results)} repo cache(s) checked, {total_dropped} stale/overflow entries dropped")
    for repo, r in results.items():
        if r.get("before"):
            print(f"  {repo}: {r['before']} -> {r['after']} entries")
    return results


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
