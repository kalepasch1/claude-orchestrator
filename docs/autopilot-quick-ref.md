# Autopilot — Quick Reference

## Purpose
`runner/autopilot.py` is the autonomous queue/improvement coordinator that
keeps the orchestrator moving without a human prompt.

## Agents

| Agent | Role |
|---|---|
| Recovery | Sweeps for missing-branch / tested-but-unintegrated tasks |
| Blocker | Remediates stale RUNNING, BLOCKED, CONFLICT, TESTFAIL states |
| Merge/Deploy | Runs the canonical merge train, release train, deploy verification |
| Ranking | EV/min ranking + prewarm for next claimable rows |
| Sample | Coder canaries so routing keeps learning |
| Dedup | Collapses duplicate queued work under deep backlog |
| Improvement | Stocks the improve-* queue (cheaply, only when low) |
| Portfolio | Preserves original revenue/attention autopilot behavior |

## Design Notes
- Every agent is bounded, fail-soft, and interval-gated through a local state
  file so the module can run frequently without redundant work.
- Prefers no-spend paths by default; improvement mining uses deterministic
  fallback ideas unless `ORCH_AUTOPILOT_MODEL_MINING=true` is explicitly set.
