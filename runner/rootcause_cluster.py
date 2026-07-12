#!/usr/bin/env python3
"""
rootcause_cluster.py - cluster BLOCKED/regression failures into named patterns.
For each recurring pattern, auto-write a permanent fix or guard rule.
"""
from __future__ import annotations
import collections, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MIN_CLUSTER_SIZE = int(os.environ.get("ORCH_CLUSTER_MIN_SIZE", "3"))
SWEEP_LIMIT = int(os.environ.get("ORCH_CLUSTER_SWEEP_LIMIT", "200"))
GUARD_KIND = "bugfix"

PATTERNS = [
    ("under-specified-task",
     re.compile(r"under-specified|no concrete implementation|PREFLIGHT DIRECTIVE.*NO:", re.I | re.S),
     "Task prompt too vague. Re-scope with concrete file targets."),
    ("agentic-repair-loop",
     re.compile(r"AGENTIC-REPAIR.*AGENTIC-REPAIR|remediation cap \d+ reached", re.I | re.S),
     "Task stuck in repair loop. Needs human re-scope or deletion."),
    ("missing-branch",
     re.compile(r"branch.*missing|no longer exists|prior branch is missing", re.I),
     "Branch was lost. Reconstruct from artifacts or start fresh."),
    ("build-tool-missing",
     re.compile(r"(yarn|pnpm|nuxt|next|vite).*command not found|command not found.*(yarn|pnpm|nuxt|next|vite)|cannot find module", re.I),
     "Build tool not installed in runner environment."),
    ("merge-conflict",
     re.compile(r"HTTP Error 409|merge.*conflict|rebase.*conflict", re.I),
     "Persistent merge conflicts."),
    ("timeout",
     re.compile(r"timed? out|timeout|deadline exceeded", re.I),
     "Network/API timeout."),
    ("budget-blocked",
     re.compile(r"budget cap|budget guard|cost circuit|capacity circuit", re.I),
     "Blocked by budget/capacity limits."),
    ("build-failure",
     re.compile(r"BUILDFAIL|build error|build red|production build.*fail", re.I),
     "Recurring build failures."),
    ("test-failure",
     re.compile(r"tests? failed|pytest.*FAILED|vitest.*fail", re.I),
     "Recurring test failures."),
]

def classify(note):
    if not note:
        return ("unclassified", "")
    for name, regex, desc in PATTERNS:
        if regex.search(note):
            return (name, desc)
    return ("unclassified", "")

def cluster_failures(project_id, limit=SWEEP_LIMIT):
    try:
        rows = db.select("tasks", {
            "select": "id,slug,project_id,note,state,kind,base_branch,updated_at",
            "project_id": f"eq.{project_id}",
            "state": "in.(BLOCKED,SHELVED)",
            "order": "updated_at.desc", "limit": str(limit),
        }) or []
    except Exception:
        return {}
    clusters = collections.defaultdict(list)
    for row in rows:
        pattern_name, _ = classify(row.get("note") or "")
        clusters[pattern_name].append(row)
    return dict(clusters)


def _guard_slug(pattern_name):
    return f"guard-cluster-{pattern_name}"[:80]

def create_cluster_guards(project_id, base_branch="master"):
    clusters = cluster_failures(project_id)
    created = []
    for pattern_name, tasks in clusters.items():
        if pattern_name == "unclassified" or len(tasks) < MIN_CLUSTER_SIZE:
            continue
        _, desc = classify(tasks[0].get("note", ""))
        slugs = [t.get("slug", "") for t in tasks[:5]]
        guard = {
            "project_id": project_id, "slug": _guard_slug(pattern_name),
            "kind": GUARD_KIND, "state": "QUEUED",
            "prompt": (f"Permanent fix for recurring '{pattern_name}' ({len(tasks)} hits). "
                       f"{desc} Affected: {', '.join(slugs)}. Add a guard."),
            "base_branch": base_branch, "deps": [],
            "note": f"auto-cluster-guard: {pattern_name} ({len(tasks)} hits)",
        }
        try:
            result = db.insert("tasks", guard)
            if result:
                created.append(result if isinstance(result, dict) else guard)
        except Exception:
            pass
    return created

def summary(project_id):
    clusters = cluster_failures(project_id)
    report = {}
    for name, tasks in sorted(clusters.items(), key=lambda x: -len(x[1])):
        _, desc = classify(tasks[0].get("note", "")) if tasks else ("", "")
        report[name] = {"count": len(tasks), "description": desc,
                        "sample_slugs": [t.get("slug", "") for t in tasks[:5]]}
    return report
