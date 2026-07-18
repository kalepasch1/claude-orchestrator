# Task State Machine

Tasks in the `tasks` table transition through these states:

```
QUEUED ──► RUNNING ──► DONE ──► MERGED
  ▲            │         │
  │            ▼         ▼
  └──── RETRY      TESTFAIL / CONFLICT
               │
               ▼
           BLOCKED
           QUARANTINED
           DECOMPOSED
```

## State definitions

- **QUEUED** — ready for claim. `db.claim_task()` atomically transitions
  QUEUED → RUNNING with an optimistic PATCH so two runners never double-claim.
- **RUNNING** — claimed by an executor (`account` column identifies which).
  Heartbeated via `updated_at`; stale runners (>90 min) are zombie-released
  back to QUEUED.
- **DONE** — implementation committed and pushed to `agent/{slug}` branch.
  Awaiting merge-train pickup.
- **MERGED** — branch merged to the base branch by the merge train.
- **RETRY** — transient failure; eligible for re-claim on next loop.
- **TESTFAIL** — tests failed post-implementation.
- **CONFLICT** — merge conflict detected during merge-train.
- **BLOCKED** — cannot proceed (e.g., budget cap, missing repo).
- **QUARANTINED** — invalid or binary-only prompt; will not be retried.
- **DECOMPOSED** — replaced by child tasks from planner decomposition.

## Transition rules

Only `QUEUED` tasks are eligible for claim. The `attempt` column tracks
how many times a task has been tried. Kill-switch and waste-guard can
return a RUNNING task to QUEUED without incrementing `attempt`.
