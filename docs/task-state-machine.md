# Task State Machine

## States
- **QUEUED** — ready to be claimed by an executor.
- **RUNNING** — claimed; executor is implementing.
- **DONE** — code committed and pushed to agent branch.
- **MERGED** — release train merged into production branch.
- **BLOCKED** — repo path missing; requires operator intervention.
- **QUARANTINED** — binary-only patch stub; no actionable English intent.

## Transitions
```
QUEUED → RUNNING     (executor claims via atomic CTE)
RUNNING → DONE       (commit + push succeed)
RUNNING → QUEUED     (zombie release after 90 min stale heartbeat)
DONE → MERGED        (release train promotes)
QUEUED → BLOCKED     (repo path does not exist)
QUEUED → QUARANTINED (hex-only PATCH TEMPLATE stub)
```
