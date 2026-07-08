#!/usr/bin/env python3
"""One-off: pin the 2026-07-08 optimization batch to the top of the claim order.
Live schema lacks tasks.priority, so prepend batch task ids to controls.ev_ranking
(and thermal_ranking), which claim_task consumes. ev_scheduler re-ranks over time.
Run: set -a; source runner/.env; set +a; python3 scripts/bump_0708_batch.py
Idempotent. Delete after the batch drains."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runner"))
import db

SLUGS = [
    "warroom-email-bridge-hardening", "cron-market-data-fail-closed", "workflow-trigger-persistence",
    "ioi-lifecycle-hardening", "otc-generator-validation", "product-gates-and-secret-separation",
    "app-ui-error-loading-states",
    "application-state-machine-guard", "pii-encryption-and-portal-rls", "audit-logger-reliability",
    "ai-call-hygiene-sweep", "rlo-review-gates", "rate-limit-and-body-limit-hardening",
    "service-role-least-privilege", "dashboard-escaping-and-a11y",
    "portal-token-hardening", "auth-required-and-regression-coverage", "oauth-token-encryption",
    "coordination-workspace-guards", "apparently-export-integration", "email-ingestion-robustness",
    "coworker-scoring-auditability", "ui-token-contract-sweep",
    "ai-safety-hardening", "purchase-gate-and-rls-verification",
    "auth-gate-audit", "vendor-seam-and-prod-guards",
    "require-ownership-coverage", "writeback-invariant-enforcement", "reshop-backoff-and-hygiene",
    "bandit-outcome-decontamination", "privacy-scrub-completion", "intake-watcher-robustness",
    "meta-optimizer-loops", "spec-drift-reconciliation",
    "fleet-pattern-library", "merge-propagation-loop", "convention-sync-fleetwide",
    "fleet-health-dashboard-panel",
    "agent-adapter-layer", "vendor-adapters-cli", "vendor-aware-routing-and-prompts",
    "web-task-composer", "web-live-run-console", "web-session-launcher",
    "capability-activation-registry",
]

# Live schema has no tasks.priority and controls is scope/paused-shaped, so use the
# ev_scheduler-sanctioned last resort: tasks.confidence as claim-order rank
# (claim_task._confidence_rank sorts by -confidence; merge gate recomputes from the
# real diff at integrate time, so this only affects claim order, never merge safety).
rows = db.select("tasks", {"select": "id,slug,state,confidence",
                           "slug": "in.(" + ",".join(SLUGS) + ")",
                           "state": "eq.QUEUED"}) or []
by_slug = {r["slug"]: r for r in rows}
print(f"queued batch tasks found: {len(rows)} of {len(SLUGS)}")
n = len(SLUGS)
bumped = 0
for i, s in enumerate(SLUGS):
    r = by_slug.get(s)
    if not r:
        print("missing/not-queued:", s); continue
    conf = round(0.99 - (i / max(n, 1)) * 0.04, 4)  # 0.99 down to ~0.95, preserves batch order
    db.update("tasks", {"id": r["id"]}, {"confidence": conf})
    bumped += 1
print(f"bumped={bumped}")
