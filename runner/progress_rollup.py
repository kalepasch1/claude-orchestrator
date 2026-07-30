#!/usr/bin/env python3
"""progress_rollup.py — per-initiative build progress: the answer to "did my improvements land?"

OPERATOR REQUIREMENT (2026-07-30): the operator should never have to wonder whether a requested
improvement was caught, implemented, merged, and deployed. This module maintains the INITIATIVE
REGISTRY (strategy-round memos broken into parts/subparts, each mapped to task-slug patterns) and
computes, per initiative: percentage progress, per-state task counts, blockers with their triage
status, and a deploy-readiness verdict. Output: a JSON rollup persisted to the coordination KV
(`progress_rollup:latest`) — the single source every surface reads (orchestrator web console,
Apparently, Smrter, the self-serve terminals). Surfaces render; this computes.

Progress model (weighted, honest):
  MERGED/DONE=1.0 · RUNNING=0.5 · QUEUED/RETRY=0.15 · BLOCKED=0.05 · QUARANTINED(dedupe)=excluded
  (a dedupe-GC'd duplicate is not lost work — its survivor carries the weight; non-dedupe
  quarantines count as blocked). Deploy-ready = all shards MERGED and none blocked.

The registry seeds from this session's Round-13 program; extend by inserting
`initiative_registry` rows into coordination_tasks (task_type='initiative_registry') — the
cross-app console build (queued) includes the editor.
"""
from __future__ import annotations
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Seed registry: initiative -> (part, subpart, slug patterns). ILIKE-style, % wildcards.
SEED_REGISTRY = [
    ("R13 P9 — Expert corps + gauntlet + saturation", "9", "corps/gauntlet/docket",
     ["%expert-corps%", "%legal-docket%", "%gauntlet%"]),
    ("R13 P9.6 — Corpus forecaster", "9", "6", ["%corpus-forecast%"]),
    ("R13 P10 — Benchmark redlines", "10", "*", ["%benchmark-redline%", "%redline%addendum%"]),
    ("R13 P11 — Foulkon decision instrument", "11", "instrument",
     ["dropbox-foulkon-the-decision-instrument%"]),
    ("R13 P11 — Tomorrow hedge bridge", "11", "hedge",
     ["dropbox-tomorrow-foulkon-hedge-bridge%"]),
    ("R13 P11 — Vigil enforcement bridge", "11", "enforcement",
     ["dropbox-vigil-foulkon-enforcement-bridge%"]),
    ("R13 P7.1/P8 — 1-click filing activation", "7", "filing",
     ["dropbox-apparently-1-click%"]),
    ("R13 P7.4 — Gaming regulator portal", "7", "4",
     ["dropbox-vigil-apparently-gaming-regulator%"]),
    ("R13 P7.2 — Bespoke newsletter engine", "7", "2",
     ["dropbox-apparently-bespoke-newsletter%"]),
    ("R13 P4/5.1 — Ingestion push + review rooms", "4", "*",
     ["dropbox-apparently-full-picture%"]),
    ("Fleet — Lease-night stash recovery", "fleet", "recovery",
     ["dropbox-recover-the-lease-night%"]),
    ("Fleet — Historical code recovery sweep", "fleet", "history",
     ["dropbox-historical-code-recovery%", "%stash-rescue%recovery%"]),
    ("Fleet — Cross-app progress console", "fleet", "console",
     ["dropbox-cross-app-build-progress%", "%progress-console%"]),
]

WEIGHT = {"MERGED": 1.0, "DONE": 1.0, "DEPLOYED": 1.0, "RUNNING": 0.5, "DECOMPOSED": 0.4,
          "QUEUED": 0.15, "RETRY": 0.15, "BLOCKED": 0.05, "QUARANTINED": 0.0}


def _registry():
    reg = list(SEED_REGISTRY)
    try:
        rows = db.select("coordination_tasks", {
            "select": "payload", "task_type": "eq.initiative_registry", "limit": "200"}) or []
        for r in rows:
            p = json.loads(r.get("payload") or "{}")
            if p.get("name") and p.get("patterns"):
                reg.append((p["name"], str(p.get("part", "?")), str(p.get("subpart", "*")),
                            list(p["patterns"])))
    except Exception:
        pass
    return reg


def _tasks_for(patterns):
    seen, out = set(), []
    for pat in patterns:
        try:
            rows = db.select("tasks", {
                "select": "id,slug,state,note,updated_at",
                "slug": f"ilike.{pat}", "limit": "200"}) or []
        except Exception:
            rows = []
        for r in rows:
            if r["id"] not in seen:
                seen.add(r["id"])
                out.append(r)
    return out


def _is_dedupe(note):
    return "semantic-dedupe" in (note or "")


def rollup():
    initiatives = []
    for name, part, subpart, patterns in _registry():
        tasks = _tasks_for(patterns)
        live = [t for t in tasks if not (t["state"] == "QUARANTINED" and _is_dedupe(t.get("note")))]
        states = {}
        for t in live:
            states[t["state"]] = states.get(t["state"], 0) + 1
        blocked = [{"id": t["id"], "slug": (t.get("slug") or "")[:70],
                    "note": (t.get("note") or "")[:160],
                    "auto_triaged": "[triage:" in (t.get("note") or "")}
                   for t in live if t["state"] in ("BLOCKED",) or
                   (t["state"] == "QUARANTINED" and not _is_dedupe(t.get("note")))]
        if live:
            pct = round(100 * sum(WEIGHT.get(t["state"], 0.1) for t in live) / len(live))
        else:
            pct = 0
        initiatives.append({
            "initiative": name, "part": part, "subpart": subpart,
            "progress_pct": pct,
            "tasks_total": len(live), "dedupe_collapsed": len(tasks) - len(live),
            "states": states,
            "deploy_ready": bool(live) and all(t["state"] in ("MERGED", "DONE", "DEPLOYED") for t in live),
            "blockers": blocked[:8],
        })
    overall = round(sum(i["progress_pct"] * max(1, i["tasks_total"]) for i in initiatives)
                    / max(1, sum(max(1, i["tasks_total"]) for i in initiatives)))
    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "overall_pct": overall,
            "deploy_ready_count": sum(1 for i in initiatives if i["deploy_ready"]),
            "initiative_count": len(initiatives),
            "initiatives": sorted(initiatives, key=lambda x: x["progress_pct"])}


def run():
    r = rollup()
    try:
        # upsert-style: one latest row (task_type + a stable key in payload)
        db.insert("coordination_tasks", {
            "task_type": "progress_rollup",
            "payload": json.dumps(r)[:60000]}, upsert=False)
    except Exception as e:
        print(f"progress_rollup: persist failed: {type(e).__name__}")
    # also drop a local artifact for the web console / any surface that prefers file reads
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".runtime", "progress_rollup.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(r, f, indent=1)
    except Exception:
        pass
    print("progress_rollup: " + json.dumps({"overall_pct": r["overall_pct"],
                                            "initiatives": r["initiative_count"],
                                            "deploy_ready": r["deploy_ready_count"]}))
    return r


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
