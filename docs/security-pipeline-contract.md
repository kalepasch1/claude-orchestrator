# Security Pipeline Contract

Codifies the security guardrails enforced by the orchestration pipeline,
analogous to the legal-radar gate documented in the merged
`dropbox-mission-legal-radar-v2` task.

## Legal Gate

The legal gate activates **owner-only** review when a proposed change would:

- Force licensing, registration, custody, or transmission obligations
- Introduce or modify advice-like outputs
- Require a secret (API key, signing key, credential)

All other changes proceed through the standard QA panel.

## Deploy-Cost Rule

- Never run `vercel --prod` or equivalent CLI production deploy
- Never push to `main`/`master` directly
- Push only the task branch (`agent/<slug>`)
- The verified batch release train promotes to production

## Coordination Rule

- Reconcile with active loop-generated work
- Reuse prior solutions first
- Do not delete or overwrite unrelated queued improvements
- Leave recovered work in the queue until shipped

## Cross-Learning Signals

The pipeline tracks per-model outcome signals (merge rate, test-pass
rate, cost) and uses learned routes to assign coders. Operator feedback
on bottlenecks feeds back into the strategy planner's model selection.
