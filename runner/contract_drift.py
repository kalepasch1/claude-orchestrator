#!/usr/bin/env python3
"""
contract_drift.py - detect capability contract drift across consuming projects.

For each published capability that declares a golden fixture (golden_ref path), enumerate
consuming projects and compute which consumers have diverged from the golden contract.
Disagreement files ONE reconciliation task per drifted consumer via the same task-insert
path candidate_shared uses (reuses db.insert). The scheduled entry point is guarded and
callable from ev_scheduler/cron.

Pure functions (detect_divergence, build_plan) are unit-testable with fixtures.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def detect_divergence(expected_golden, observed_results):
    """PURE: compare expected golden fixture against observed results.
    Returns list of drifted field dicts: [{"field": ..., "expected": ..., "observed": ...}].
    Both inputs are dicts (or JSON-parseable strings).
    """
    if isinstance(expected_golden, str):
        try:
            expected_golden = json.loads(expected_golden)
        except (json.JSONDecodeError, TypeError):
            expected_golden = {}
    if isinstance(observed_results, str):
        try:
            observed_results = json.loads(observed_results)
        except (json.JSONDecodeError, TypeError):
            observed_results = {}
    if not isinstance(expected_golden, dict) or not isinstance(observed_results, dict):
        return []

    drifted = []
    for key, expected_val in expected_golden.items():
        observed_val = observed_results.get(key)
        if observed_val != expected_val:
            drifted.append({
                "field": key,
                "expected": expected_val,
                "observed": observed_val,
            })
    return drifted


def build_plan(capabilities, consumers_by_cap):
    """PURE: build a plan of which consumers to run the golden against.
    capabilities: list of dicts with at least {slug, golden_ref}
    consumers_by_cap: dict of cap_slug -> list of {project_id, project_name}
    Returns list of {cap_slug, golden_ref, project_id, project_name}.
    """
    plan = []
    for cap in capabilities:
        slug = cap.get("slug", "")
        golden = cap.get("golden_ref")
        if not golden:
            continue
        consumers = consumers_by_cap.get(slug, [])
        for c in consumers:
            plan.append({
                "cap_slug": slug,
                "golden_ref": golden,
                "project_id": c.get("project_id", ""),
                "project_name": c.get("project_name", ""),
            })
    return plan


def _load_golden(golden_ref):
    """Load a golden fixture from a file path or return empty dict."""
    if not golden_ref or not os.path.isfile(golden_ref):
        return {}
    try:
        with open(golden_ref, "r", errors="replace") as f:
            return json.load(f)
    except Exception:
        return {}


def run():
    """Scheduled entry point: detect drift and file reconciliation tasks."""
    # Fetch capabilities with golden_ref
    caps = db.select("capabilities", {
        "select": "slug,golden_ref,name",
        "golden_ref": "not.is.null"}) or []
    if not caps:
        return

    # Fetch consuming projects per capability
    consumers_by_cap = {}
    for cap in caps:
        slug = cap.get("slug", "")
        consumers = db.select("capability_consumers", {
            "select": "project_id,project_name",
            "capability_slug": f"eq.{slug}"}) or []
        if consumers:
            consumers_by_cap[slug] = consumers

    plan = build_plan(caps, consumers_by_cap)
    if not plan:
        return

    for item in plan:
        golden = _load_golden(item["golden_ref"])
        if not golden:
            continue

        # For each consumer, check if observed results match golden
        observed = db.select("capability_results", {
            "select": "results",
            "capability_slug": f"eq.{item['cap_slug']}",
            "project_id": f"eq.{item['project_id']}",
            "order": "created_at.desc",
            "limit": "1"}) or []
        if not observed:
            continue

        obs_data = observed[0].get("results", {})
        drifted = detect_divergence(golden, obs_data)
        if not drifted:
            continue

        # File one reconciliation task per drifted consumer
        task_slug = f"drift-reconcile-{item['cap_slug']}-{item['project_id'][:8]}"
        drift_summary = "; ".join(f"{d['field']}: expected={d['expected']}, got={d['observed']}" for d in drifted[:5])
        db.insert("tasks", {
            "slug": task_slug,
            "project_id": item["project_id"],
            "state": "QUEUED",
            "kind": "chore",
            "prompt": f"Reconcile capability contract drift for '{item['cap_slug']}' in project "
                      f"'{item['project_name']}'. Drifted fields: {drift_summary}",
        })
