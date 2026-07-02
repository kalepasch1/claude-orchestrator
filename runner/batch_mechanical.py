#!/usr/bin/env python3
"""
batch_mechanical.py - kill cold-start overhead on the cheap long tail. Each agent run pays a fixed
cost (spawn worktree, load context, model warmup). Running 20 one-line lint/rename/doc tasks as 20
separate agent runs wastes most of the budget on overhead. This groups INDEPENDENT mechanical tasks
in the SAME repo into a single combined task, so one Haiku run does all of them in one worktree.

Safety rules (conservative on purpose):
  * Only tasks classified MECHANICAL by model_router (lint/format/rename/doc/theme/etc).
  * Only tasks with NO deps and that NOTHING depends on (leaf, independent) — so merging them can't
    reorder or break a dependency chain.
  * Only within the SAME project/repo, capped at BATCH_MAX per group.
  * The combined task keeps the original slugs in its body and lists them so provenance is clear.
    Originals are marked MERGED-INTO (state stays out of the queue) and the batch task is QUEUED.

This never touches feature/heavy tasks or anything in a dependency relationship.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, model_router

BATCH_MAX = int(os.environ.get("BATCH_MAX", "8"))
MIN_GROUP = int(os.environ.get("BATCH_MIN", "3"))       # don't bother batching < this many


MECH_MAX_PROMPT = int(os.environ.get("BATCH_MECH_MAX_PROMPT", "600"))


def _is_mechanical(prompt):
    """TRUE only for genuinely mechanical work. Must NOT rely on the router's default tier — since
    Haiku-first routing makes Haiku the default for ALL work, that signal would (and did) misclassify
    substantive feature tasks as mechanical. Require a real mechanical keyword, NO heavy signal, and
    a short prompt (real chores are small)."""
    p = prompt or ""
    if len(p) > MECH_MAX_PROMPT:
        return False
    if model_router.HEAVY.search(p):
        return False
    return bool(model_router.MECHANICAL.search(p))


def find_batches():
    tasks = db.select("tasks", {"select": "id,slug,prompt,deps,state,project_id,base_branch",
                                "state": "eq.QUEUED"}) or []
    # slugs that are depended upon by ANY task (can't batch those away)
    depended = set()
    for t in db.select("tasks", {"select": "deps"}) or []:
        for d in (t.get("deps") or []):
            depended.add(d)
    groups = {}
    for t in tasks:
        if t.get("deps"):
            continue                      # has upstream deps -> skip
        if t["slug"] in depended:
            continue                      # something depends on it -> skip
        if (t.get("slug") or "").startswith("batch-mech-"):
            continue                      # never re-batch a batch (prevents nested batch-mech-batch-mech)
        if not _is_mechanical(t.get("prompt")):
            continue
        groups.setdefault(t["project_id"], []).append(t)
    # keep only groups worth batching
    return {pid: ts[:BATCH_MAX] for pid, ts in groups.items() if len(ts) >= MIN_GROUP}


def analyze():
    batches = find_batches()
    return [{"project_id": pid, "count": len(ts), "slugs": [t["slug"] for t in ts]}
            for pid, ts in batches.items()]


def apply():
    batches = find_batches()
    made = 0
    for pid, ts in batches.items():
        slugs = [t["slug"] for t in ts]
        base = ts[0].get("base_branch") or "main"
        combined = ("Complete ALL of the following small, independent mechanical changes in one pass. "
                    "Do each fully and keep them isolated to their own files:\n\n" +
                    "\n".join(f"{i+1}. [{t['slug']}] {t['prompt']}" for i, t in enumerate(ts)))
        batch_slug = f"batch-mech-{slugs[0]}-{len(slugs)}"
        db.insert("tasks", {"project_id": pid, "slug": batch_slug, "prompt": combined,
                            "base_branch": base, "kind": "mechanical", "state": "QUEUED",
                            "deps": [], "model": model_router.HAIKU,
                            "note": f"batched {len(slugs)} mechanical tasks: {', '.join(slugs)}"})
        # take the originals out of the queue (folded into the batch)
        for t in ts:
            db.update("tasks", {"id": t["id"]},
                      {"state": "DONE", "note": f"folded into {batch_slug}", "updated_at": "now()"})
        made += 1
        print(f"batch_mechanical: folded {len(slugs)} tasks -> {batch_slug}")
    if not made:
        print("batch_mechanical: no batchable mechanical groups found")
    return made


if __name__ == "__main__":
    import json
    if len(sys.argv) > 1 and sys.argv[1] == "apply":
        print("batches made:", apply())
    else:
        print(json.dumps(analyze(), indent=2))
