#!/usr/bin/env python3
"""
branch_reconciler.py - reconcile stuck unmerged branches.

Scans unmerged agent/* branches, extracts build failure reasons (via
build_gate), clusters branches by their missing dependency (e.g. same
missing module, same missing table), and generates foundation task
proposals for each cluster so the root dependency can be fixed once.

Feature flag: ORCH_BRANCH_RECONCILER_ENABLED (default true)
Fail-soft: every public function returns a safe default on error.
"""
import os, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import build_gate

ENABLED = os.environ.get("ORCH_BRANCH_RECONCILER_ENABLED", "true").lower() in ("1", "true", "yes", "on")


def scan_unmerged(repo=None):
    """Get all unmerged agent/* branches with their failure reasons.

    Returns list of dicts: [{branch, has_failures, reasons: [{type, detail}]}]
    Fail-soft: returns [] on error.
    """
    if not ENABLED:
        return []
    try:
        branches = build_gate.scan_branches(repo)
        results = []
        for branch in branches:
            status = build_gate.check_build_status(branch, repo=repo)
            results.append(status)
        return results
    except Exception:
        return []


def cluster_by_dependency(failures):
    """Group branches by their missing dependency.

    Input: list of dicts from scan_unmerged (each has branch, reasons).
    Output: dict of dependency_key -> [branch_info, ...]

    The dependency_key is "type:detail" (e.g. "missing_module:utils.helpers",
    "missing_table:accounts").  Branches with no detected failures are grouped
    under "unknown".
    """
    if not failures:
        return {}
    clusters = defaultdict(list)
    for entry in failures:
        branch = entry.get("branch", "")
        reasons = entry.get("reasons", [])
        if not reasons:
            clusters["unknown"].append(entry)
            continue
        # A branch may have multiple failure reasons; assign to the first
        # actionable one (missing_module, missing_table, missing_file first)
        priority_order = [
            "missing_module", "missing_table", "missing_column",
            "missing_file", "import_error",
        ]
        assigned = False
        for ptype in priority_order:
            for reason in reasons:
                if reason.get("type") == ptype:
                    key = f"{ptype}:{reason['detail']}"
                    clusters[key].append(entry)
                    assigned = True
                    break
            if assigned:
                break
        if not assigned:
            # Use the first reason as the cluster key
            r = reasons[0]
            key = f"{r['type']}:{r.get('detail', 'unknown')}"
            clusters[key].append(entry)
    return dict(clusters)


def generate_proposals(clusters):
    """For each cluster, generate a task proposal that fixes the root dependency.

    Input: dict from cluster_by_dependency.
    Output: list of proposal dicts, one per cluster:
        [{dependency_key, affected_branches, proposal: {slug, prompt, kind}}]
    """
    if not clusters:
        return []
    proposals = []
    for dep_key, entries in clusters.items():
        affected = [e.get("branch", "") for e in entries]
        parts = dep_key.split(":", 1)
        dep_type = parts[0] if parts else "unknown"
        dep_detail = parts[1] if len(parts) > 1 else "unknown"

        # Generate a slug and prompt based on the dependency type
        if dep_type == "missing_module":
            slug = f"foundation-create-{dep_detail.replace('.', '-')}"
            prompt = (f"Create the missing Python module '{dep_detail}' that "
                      f"{len(affected)} agent branch(es) depend on. "
                      f"Affected branches: {', '.join(affected[:5])}")
        elif dep_type == "missing_table":
            slug = f"foundation-create-table-{dep_detail.replace('.', '-')}"
            prompt = (f"Create the missing database table '{dep_detail}' that "
                      f"{len(affected)} agent branch(es) need. "
                      f"Affected branches: {', '.join(affected[:5])}")
        elif dep_type == "missing_column":
            slug = f"foundation-add-column-{dep_detail.replace('.', '-')}"
            prompt = (f"Add the missing column '{dep_detail}' that "
                      f"{len(affected)} agent branch(es) reference. "
                      f"Affected branches: {', '.join(affected[:5])}")
        elif dep_type == "missing_file":
            slug = f"foundation-create-file-{os.path.basename(dep_detail)}"
            prompt = (f"Create the missing file '{dep_detail}' that "
                      f"{len(affected)} agent branch(es) require. "
                      f"Affected branches: {', '.join(affected[:5])}")
        elif dep_type == "import_error":
            slug = f"foundation-fix-import-{dep_detail.replace('.', '-')}"
            prompt = (f"Fix the import error for '{dep_detail}' that blocks "
                      f"{len(affected)} agent branch(es). "
                      f"Affected branches: {', '.join(affected[:5])}")
        else:
            slug = f"foundation-fix-{dep_type}-{dep_detail[:30].replace(' ', '-')}"
            prompt = (f"Fix the root cause ({dep_type}: {dep_detail}) blocking "
                      f"{len(affected)} agent branch(es). "
                      f"Affected branches: {', '.join(affected[:5])}")

        proposals.append({
            "dependency_key": dep_key,
            "affected_branches": affected,
            "proposal": {
                "slug": slug,
                "prompt": prompt,
                "kind": "foundation",
            },
        })
    return proposals


def reconcile(repo=None):
    """Orchestrate: scan -> cluster -> propose.

    Returns dict: {branches_scanned, clusters, proposals, error?}
    Fail-soft: returns a safe summary on any error.
    """
    if not ENABLED:
        return {"branches_scanned": 0, "clusters": {}, "proposals": [], "skipped": "disabled"}
    try:
        scanned = scan_unmerged(repo)
        # Only cluster branches that have failures
        with_failures = [s for s in scanned if s.get("has_failures")]
        clusters = cluster_by_dependency(with_failures)
        proposals = generate_proposals(clusters)
        return {
            "branches_scanned": len(scanned),
            "branches_with_failures": len(with_failures),
            "clusters": clusters,
            "proposals": proposals,
        }
    except Exception as e:
        return {"branches_scanned": 0, "clusters": {}, "proposals": [], "error": str(e)}


def stats():
    """Module statistics."""
    try:
        result = reconcile()
        return {
            "enabled": ENABLED,
            "branches_scanned": result.get("branches_scanned", 0),
            "branches_with_failures": result.get("branches_with_failures", 0),
            "cluster_count": len(result.get("clusters", {})),
            "proposal_count": len(result.get("proposals", [])),
        }
    except Exception:
        return {"enabled": ENABLED, "branches_scanned": 0, "cluster_count": 0, "proposal_count": 0}
