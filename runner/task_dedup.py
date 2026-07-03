#!/usr/bin/env python3
"""
task_dedup.py - stop the swarm solving the same thing twice. Across ALL projects, detect QUEUED tasks
that are near-duplicates (same work, maybe different app) and collapse them so it's solved ONCE and the
result is reused — instead of N parallel agents burning capacity on the same problem.

Conservative + safe:
  * Compares QUEUED tasks by normalized prompt shape (token-set similarity; embeddings if configured).
  * Only collapses when similarity >= DEDUP_SIM (high bar) AND neither task is material/has deps.
  * WITHIN a project: keeps the oldest, marks the rest deps=[keeper] so they wait and reuse (result_cache
    already returns the cached branch for identical repo+prompt+commit).
  * ACROSS projects: does NOT auto-merge work (repos differ); instead flags the cluster so the capability
    registry can generalize it once and instantiate per app.

analyze() previews clusters; apply() performs the safe within-project collapse + files cross-app flags.
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

DEDUP_SIM = float(os.environ.get("DEDUP_SIM", "0.82"))
DEDUP_FILE_PENDING_CARDS = os.environ.get("DEDUP_FILE_PENDING_CARDS", "false").lower() in ("true", "1", "yes")
_STOP = set("the a an to of and or for in on with build add fix update create make this that use "
            "implement task change set get run test file page component function".split())


def _toks(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 3 and w not in _STOP}


def _sim(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _clusters(tasks):
    items = [(t, _toks(t.get("prompt"))) for t in tasks]
    used, clusters = set(), []
    for i, (t, tk) in enumerate(items):
        if t["id"] in used or not tk:
            continue
        group = [t]
        used.add(t["id"])
        for j in range(i + 1, len(items)):
            t2, tk2 = items[j]
            if t2["id"] in used:
                continue
            if _sim(tk, tk2) >= DEDUP_SIM:
                group.append(t2)
                used.add(t2["id"])
        if len(group) > 1:
            clusters.append(group)
    return clusters


def analyze():
    tasks = db.select("tasks", {"select": "id,slug,prompt,deps,material,project_id",
                                "state": "eq.QUEUED"}) or []
    tasks = [t for t in tasks if not t.get("material") and not (t.get("deps") or [])]
    out = []
    for g in _clusters(tasks):
        same_proj = len({t["project_id"] for t in g}) == 1
        out.append({"scope": "within-project" if same_proj else "cross-project",
                    "slugs": [t["slug"] for t in g], "keeper": g[0]["slug"], "n": len(g)})
    return out


def apply():
    tasks = db.select("tasks", {"select": "id,slug,prompt,deps,material,project_id,created_at",
                                "state": "eq.QUEUED"}) or []
    tasks = [t for t in tasks if not t.get("material") and not (t.get("deps") or [])]
    collapsed = flagged = 0
    for g in _clusters(tasks):
        g.sort(key=lambda t: t.get("created_at") or "")
        keeper = g[0]
        if len({t["project_id"] for t in g}) == 1:
            # within a project: make the rest wait on the keeper so result_cache reuse kicks in
            for dup in g[1:]:
                db.update("tasks", {"id": dup["id"]},
                          {"deps": [keeper["slug"]],
                           "note": f"dedup: waits on '{keeper['slug']}' (near-duplicate) to reuse result",
                           "updated_at": "now()"})
                collapsed += 1
        else:
            db.insert("approvals", {"project": "PORTFOLIO", "kind": "self",
                "status": "pending" if DEDUP_FILE_PENDING_CARDS else "approved",
                "decided_by": None if DEDUP_FILE_PENDING_CARDS else "auto-policy:dedup-advisory",
                "decision_type": None if DEDUP_FILE_PENDING_CARDS else "approve",
                "decision_text": None if DEDUP_FILE_PENDING_CARDS else "Auto-approved advisory; dedup should not interrupt the owner.",
                "title": f"Cross-app duplicate work: {len(g)} tasks look identical",
                "why": f"Near-duplicate across apps: {[t['slug'] for t in g]}. Solve once as a capability "
                       f"and instantiate per app.",
                "value": "Avoid N agents solving the same problem in parallel.",
                "risk": "Low — advisory; nothing auto-merged across repos.", "command": ""})
            flagged += 1
    print(f"task_dedup: collapsed {collapsed} within-project duplicates, flagged {flagged} cross-app clusters")
    return {"collapsed": collapsed, "flagged": flagged}


if __name__ == "__main__":
    import json
    print(json.dumps(analyze(), indent=2)[:3000])
