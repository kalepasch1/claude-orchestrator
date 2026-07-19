#!/usr/bin/env python3
"""
rca_engine.py — autonomous root cause analysis for task failures.

Ingests QUARANTINED and BLOCKED task metadata, groups failures by
error signature, and identifies systemic root causes. Outputs
actionable remediation suggestions ranked by impact (task count).

Designed to feed into agentic_repair.py and the approval pipeline.

Env vars:
    ORCH_RCA_ENABLED       "true" to enable (default "true")
    ORCH_RCA_MIN_CLUSTER   minimum failures to form a cluster (default 3)
    ORCH_RCA_MAX_CLUSTERS  max clusters to report (default 10)
"""
import os
import re
import sys
import collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENABLED = os.environ.get("ORCH_RCA_ENABLED", "true").lower() in ("1", "true", "yes")
MIN_CLUSTER = int(os.environ.get("ORCH_RCA_MIN_CLUSTER", "3"))
MAX_CLUSTERS = int(os.environ.get("ORCH_RCA_MAX_CLUSTERS", "10"))

# Error signature patterns — map raw notes to root cause categories
_SIGNATURES = [
    (re.compile(r"repo not found|PAT lacks access", re.I), "auth-or-repo-missing"),
    (re.compile(r"rebase conflict|merge conflict", re.I), "merge-conflict"),
    (re.compile(r"tests? failed|test failure", re.I), "test-failure"),
    (re.compile(r"build fail|compilation error|tsc.*error", re.I), "build-failure"),
    (re.compile(r"timeout|timed out|max.turns", re.I), "timeout"),
    (re.compile(r"missing.branch|branch.*not found", re.I), "missing-branch"),
    (re.compile(r"rate.limit|quota|throttl", re.I), "rate-limited"),
    (re.compile(r"disk.space|no space left", re.I), "disk-space"),
    (re.compile(r"binary.*patch|hex.only|PATCH TEMPLATE", re.I), "unresolvable-template"),
    (re.compile(r"nothing to commit|no.file.changes", re.I), "no-op"),
]

_REMEDIATIONS = {
    "auth-or-repo-missing": "Verify GITHUB_PAT validity and repo access permissions.",
    "merge-conflict": "Rebase agent branches onto latest base; consider auto-rebase in merge train.",
    "test-failure": "Run failing tests locally; check if base branch tests pass first.",
    "build-failure": "Check TypeScript errors and missing imports; may need dependency update.",
    "timeout": "Increase TASK_TIMEOUT or reduce task scope via decomposition.",
    "missing-branch": "Run branch_fleet_recovery.py; check worktree cleanup.",
    "rate-limited": "Rotate API keys or increase cooldown between coder dispatches.",
    "disk-space": "Clean worktrees and prune git objects; check .runtime/ size.",
    "unresolvable-template": "Quarantine is correct — these need human re-scope.",
    "no-op": "Task may already be complete; verify and mark DONE.",
}


def classify_note(note):
    """Extract root cause category from a task note. Returns category string."""
    if not note:
        return "unknown"
    for pattern, category in _SIGNATURES:
        if pattern.search(note):
            return category
    return "unknown"


def analyze(project_id=None):
    """Analyze QUARANTINED + BLOCKED tasks and cluster by root cause.

    Returns list of clusters sorted by count descending.
    """
    if not ENABLED:
        return []
    try:
        import db
    except ImportError:
        return []

    filters = {"select": "id,slug,note,kind,attempt", "state": "in.(QUARANTINED,BLOCKED)"}
    if project_id:
        filters["project_id"] = f"eq.{project_id}"
    rows = db.select("tasks", filters) or []

    clusters = collections.Counter()
    samples = collections.defaultdict(list)
    for r in rows:
        cat = classify_note(r.get("note", ""))
        clusters[cat] += 1
        if len(samples[cat]) < 3:
            samples[cat].append({"slug": r.get("slug", ""), "note": (r.get("note") or "")[:200]})

    results = []
    for cat, count in clusters.most_common(MAX_CLUSTERS):
        if count < MIN_CLUSTER:
            break
        results.append({
            "root_cause": cat,
            "count": count,
            "remediation": _REMEDIATIONS.get(cat, "Manual investigation needed."),
            "samples": samples[cat],
        })
    return results


def run():
    """CLI entry point — print root cause analysis report."""
    clusters = analyze()
    if not clusters:
        print("rca_engine: no systemic failure clusters found")
        return []
    total = sum(c["count"] for c in clusters)
    print(f"rca_engine: {len(clusters)} root cause cluster(s), {total} total failures")
    for c in clusters:
        print(f"  [{c['count']:3d}] {c['root_cause']}: {c['remediation']}")
    return clusters


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
