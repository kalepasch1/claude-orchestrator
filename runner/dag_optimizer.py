#!/usr/bin/env python3
"""
dag_optimizer.py - keeps the task dependency graph HEALTHY so a broken/missing upstream task can
never permanently freeze its whole subtree (the failure mode that stalled `tomorrow`: 115 QUEUED
tasks, 0 claimable, all waiting on a handful of dead foundation tasks).

Three safe operations (analyze() previews; optimize() applies the safe ones):

  1. DROP GHOST DEPS  (safe, auto): a QUEUED task that lists a dep slug which does NOT exist in the
     task table can never be satisfied — that dep is a planning bug. Remove just that dep. If the
     task has other, real deps they still gate it.

  2. FLAG ORPHANS  (advisory): a QUEUED task whose only blockers are TERMINALLY dead deps (a dep
     that is BLOCKED with a terminal, over-retry-cap reason and won't auto-recover) is surfaced as
     an approval so a human can re-scope/cancel — instead of it silently sitting un-claimable.

  3. PRUNE REDUNDANT TRANSITIVE DEPS  (safe, auto, optional): if A deps on both B and C and B
     (transitively) already deps on C, A's direct edge to C is redundant. Dropping it never changes
     execution order but shrinks the graph and reduces false "unsatisfied" states.

Never touches deps that point at healthy (DONE/MERGED/QUEUED/RUNNING or transiently-retrying) tasks.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

try:
    import retry_policy
except Exception:
    retry_policy = None

TERMINAL_STATES = {"BLOCKED"}
LIVE_STATES = {"QUEUED", "RUNNING", "DONE", "MERGED", "RETRY"}


def _load():
    rows = db.select("tasks", {"select": "id,slug,state,deps,note,transient_retries,project_id"}) or []
    by_slug = {}
    for r in rows:
        by_slug.setdefault(r["slug"], r)  # first wins; slugs should be unique per project
    return rows, by_slug


def _dep_will_complete(dep_slug, by_slug):
    """Will this dep ever reach DONE/MERGED on its own? Missing -> no. Live -> yes.
    BLOCKED -> yes only if transient & under the auto-retry cap (unstick will recover it)."""
    d = by_slug.get(dep_slug)
    if d is None:
        return False, "ghost (no such task)"
    st = d.get("state")
    if st in ("DONE", "MERGED"):
        return True, "done"
    if st in ("QUEUED", "RUNNING", "RETRY"):
        return True, "live"
    if st == "BLOCKED":
        if retry_policy:
            kind = retry_policy.classify(d.get("note") or "")
            tr = int(d.get("transient_retries") or 0)
            if kind == "transient" and tr < retry_policy.MAX_TRANSIENT_RETRIES:
                return True, "transient-will-retry"
        return False, "terminally blocked"
    return False, f"state={st}"


def _reachable_deps(slug, by_slug, cache):
    """All deps reachable transitively from slug (excluding slug)."""
    if slug in cache:
        return cache[slug]
    seen = set()
    stack = list((by_slug.get(slug, {}).get("deps") or []))
    while stack:
        s = stack.pop()
        if s in seen:
            continue
        seen.add(s)
        stack.extend(by_slug.get(s, {}).get("deps") or [])
    cache[slug] = seen
    return seen


def analyze():
    rows, by_slug = _load()
    ghost_edges, orphans, redundant = [], [], []
    tcache = {}
    for t in rows:
        if t.get("state") != "QUEUED":
            continue
        deps = list(t.get("deps") or [])
        if not deps:
            continue
        # 1: ghost deps
        ghosts = [d for d in deps if d not in by_slug]
        for g in ghosts:
            ghost_edges.append({"slug": t["slug"], "dep": g})
        # 2: orphan (every remaining dep will never complete)
        real = [d for d in deps if d in by_slug]
        if real and all(not _dep_will_complete(d, by_slug)[0] for d in real):
            reasons = {d: _dep_will_complete(d, by_slug)[1] for d in real}
            orphans.append({"slug": t["slug"], "project_id": t.get("project_id"), "blockers": reasons})
        # 3: redundant transitive edges (direct dep also reachable via another direct dep)
        for d in real:
            others = [x for x in real if x != d]
            if any(d in _reachable_deps(o, by_slug, tcache) for o in others):
                redundant.append({"slug": t["slug"], "dep": d})
    return {"ghost_edges": ghost_edges, "orphans": orphans, "redundant": redundant}


def optimize(apply_redundant=True):
    """Apply the safe auto ops (drop ghost + optionally redundant edges); file cards for orphans."""
    a = analyze()
    _, by_slug = _load()
    dropped_ghost = dropped_redundant = flagged = 0

    # collect edges to drop per task, then write once
    drop = {}
    for e in a["ghost_edges"]:
        drop.setdefault(e["slug"], set()).add(e["dep"])
    if apply_redundant:
        for e in a["redundant"]:
            drop.setdefault(e["slug"], set()).add(e["dep"])

    for slug, dead in drop.items():
        t = by_slug.get(slug)
        if not t:
            continue
        new_deps = [d for d in (t.get("deps") or []) if d not in dead]
        db.update("tasks", {"id": t["id"]},
                  {"deps": new_deps, "updated_at": "now()"})
        dropped_ghost += sum(1 for e in a["ghost_edges"] if e["slug"] == slug)
        dropped_redundant += sum(1 for e in a["redundant"] if e["slug"] == slug and apply_redundant)

    for o in a["orphans"]:
        db.insert("approvals", {
            "project": None, "kind": "self",
            "title": f"Orphaned task '{o['slug']}' — deps will never complete",
            "why": f"All deps are dead: {o['blockers']}. It can't be claimed until re-scoped.",
            "value": "Re-scope or cancel so it stops sitting un-claimable.",
            "risk": "Low — advisory; nothing auto-changed on this task.", "command": ""})
        flagged += 1

    print(f"dag_optimizer: dropped {dropped_ghost} ghost + {dropped_redundant} redundant dep edges; "
          f"flagged {flagged} orphan task(s)")
    return {"ghost": dropped_ghost, "redundant": dropped_redundant, "orphans": flagged}


if __name__ == "__main__":
    import json
    if len(sys.argv) > 1 and sys.argv[1] == "apply":
        print(json.dumps(optimize(), indent=2))
    else:
        print(json.dumps(analyze(), indent=2)[:4000])
