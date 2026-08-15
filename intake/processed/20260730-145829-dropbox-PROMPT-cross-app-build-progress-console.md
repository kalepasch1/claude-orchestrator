# Cross-App Build Progress Console (orchestrator + Apparently + Smrter + all self-serve terminals)

Operator directive 2026-07-30. The operator (and eventually every terminal user on pareto, smrter,
apparently, tomorrow, and the orchestrator app) must never have to WONDER whether requested
improvements were caught, implemented, merged, and deployed. Build the console on every surface.

## The data layer EXISTS — build surfaces on it, do not re-derive
`runner/progress_rollup.py` computes per-initiative progress every 5 min (strategy-round
parts/subparts -> % progress, per-state task counts, blockers with auto-triage status,
deploy-readiness) and persists to coordination_tasks (task_type='progress_rollup', latest row)
plus `.runtime/progress_rollup.json`. `runner/blocked_triage.py` auto-remediates blocked shards
and persists triage digests (task_type='triage_digest'). Initiative registry extends via
task_type='initiative_registry' rows.

## Per surface
1. ORCHESTRATOR WEB CONSOLE (web/): the operator's master view.
   - Initiative table: every strategy-memo part/subpart as a row — progress bar %, states,
     blockers (with the auto-triage class + attempt count), deploy-ready badge.
   - THE BIG TABLE: every task/improvement/remediation submitted or agent-generated — filterable
     by initiative/state/app/source (operator-prompt vs autonomous), sortable, with full note
     history per row.
   - CONTROLS per row + per initiative: **Pause** (flip shards to a HELD state the claimer skips),
     **Resume**, **Steer** (append operator guidance to the shard prompt), **Remediate** (1-click:
     run blocked_triage classification on demand and requeue with the targeted fix), **Escalate**.
   - Notifications: initiative crossing thresholds (blocked>N, deploy-ready, regression) fans to
     the existing notification rails (email + Slack per approvalNotify pattern).
2. APPARENTLY (user-facing): "Build Progress" page per workspace scoped to THAT customer's
   requests/initiatives only (RLS) — same bars/states/notify, plus plain-language state labels.
   Reuses Apparently's outbox/notification tables.
3. SMRTER: same component, Smrter idiom, workspace-scoped.
4. SELF-SERVE TERMINALS (pareto/smrter/apparently/tomorrow/orchestrator terminal surfaces): a
   compact progress widget (top-5 initiatives + % + blocked count) with click-through to the full
   table; the Remediate button appears only for users with operator role.
5. Transport: the orchestrator exposes a small read API over the rollup (orchestration_api.py has
   the seam); app surfaces poll or SSE per their existing patterns. Cross-app auth: reuse each
   app's existing S2S HMAC pattern; NO new secret classes.

## Registry completeness (part of THIS build's acceptance)
Backfill the initiative registry from ALL strategy-round memos in
~/Documents/beethoven (PORTFOLIO_STRATEGY_V2*, PORTFOLIO_ROUND13*, the network-economics and
cost-displacement memos): every Part and named subpart becomes a registry row with its slug
patterns (mine the drop-box slugs + task table for matches). Acceptance: the operator opens the
console and sees EVERY part/subpart of every round memo with a live progress number — zero
"unknown" initiatives among tasks created in the last 30 days.

## Guardrails
- Pause/steer/remediate are audited (who, when, what) to coordination events.
- Customer surfaces NEVER see other workspaces' initiatives (RLS + tests proving it).
- The console reads rollups; it never mutates tasks except through the audited control endpoints.
