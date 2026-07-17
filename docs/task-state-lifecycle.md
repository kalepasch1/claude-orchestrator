# Task State Lifecycle

Documents the valid state transitions for tasks in the orchestrator queue.

```
QUEUED ──► RUNNING ──► DONE ──► MERGED
  │            │         │
  │            ▼         ▼
  │        BLOCKED    (terminal)
  │            │
  │            ▼
  │        QUEUED (re-queued after unblock)
  │
  ▼
QUARANTINED (binary stub or security gate)
```

## States

- **QUEUED** — Ready for an executor to claim. Tasks enter this state on creation or after zombie release.
- **RUNNING** — Claimed by an executor session. Heartbeated via `updated_at` to avoid zombie sweeps.
- **DONE** — Implementation committed and pushed to `agent/{slug}` branch.
- **MERGED** — Merge train promoted the branch to the default branch. Terminal state.
- **BLOCKED** — Executor could not proceed (e.g., repo path missing). May be re-queued after resolution.
- **QUARANTINED** — Removed from the queue due to binary-only stub or security gate. Requires manual rework task.

## Zombie Recovery

Tasks stuck RUNNING with `updated_at` older than 90 minutes are released back to QUEUED by the next executor session's Step 0b sweep.
