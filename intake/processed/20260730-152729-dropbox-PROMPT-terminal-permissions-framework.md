# Terminal Permissions Framework — admin-set, Foulkon-risk-gated (all apps with self-serve terminals)

Operator directive 2026-07-30. Every app with a self-servicing/steering/vibe-coding terminal
(pareto, smrter, apparently, tomorrow, orchestrator) gets easy admin-set permissions controlling
who can implement/push, who needs approval, and at what Foulkon-scored risk level approval kicks in.

## BASIC mode (one screen, three controls per user — a non-technical admin sets this in 60s)
Per user (and an account-wide default):
1. **Autonomy level**: Full (implement/push without approval) | Gated (approval before any
   implementation) | View-only.
2. **Risk ceiling**: a single slider bound to the Foulkon gradient score (0-100). Changes at or
   below the ceiling flow per the user's autonomy level; ABOVE the ceiling always requires
   approval regardless of level. Default ceiling: 40 (Foulkon 'review' threshold).
3. **Approver**: who approves this user's gated changes (a user, a role, or "any admin").

## ADVANCED mode (progressive disclosure — basic stays the default view)
- **Per-dimension ceilings**: separate risk ceilings for code, filings/regulatory actions,
  spend/billing-touching changes, data/schema changes, and customer-facing copy.
- **Scoped autonomy**: full autonomy limited to named repos/modules/paths (e.g., frontend-only);
  everything else gated. Uses the tribunal's `implicated_scope` to enforce.
- **Conditional rules**: "auto-approve if Foulkon ≤ 25 AND tests pass AND change < 200 lines";
  "always require approval when a pending license application is implicated (company_context)."
- **Time-boxed elevation**: grant elevated autonomy for N hours (incident response), auto-revert,
  fully audited.
- **Approval routing**: risk-banded routing (low → team lead, high → compliance, filing-class →
  attorney queue per §5.8b); SLA timers with escalation on stale approvals.
- **Learning suggestions (advisory only)**: after 30 days, suggest ceiling adjustments from the
  user's record ("approved 96% of Maya's gated changes ≤ 35 risk — raise her ceiling?"). The
  admin clicks; the system never self-adjusts permissions.

## Enforcement invariants (uniform across all five apps)
- The gate is SERVER-SIDE at the implement/push choke point of each app's terminal pipeline —
  the UI reflects permissions, never enforces them.
- Foulkon score is computed on the CHANGE (diff + context), cached with the gradient; a change
  that cannot be scored is treated as ABOVE ceiling (fail-closed).
- Every decision (auto-approved, gated, approved-by-whom, overridden) is an audit row; the
  progress console shows approvals pending per initiative.
- Account-wide kill-switch: one click sets every user to Gated (incident posture).
- Same schema everywhere (shared permission model, per-app storage following each app's RLS
  conventions); one React/Vue component family adapted per app idiom.

## Reuse
Apparently already has role/permission primitives (FirmMember roles, RoomParticipant flags) and
Tomorrow has mandate/kill-switch patterns (agent_mandates, TrustDial) — extend these, don't fork.
The TrustDial (Auto-Pilot/Co-Pilot/Counsel) is the right UX metaphor for the Basic autonomy level.
