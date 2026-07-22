# Task State Machine

Tasks move through a strict state machine. Only valid transitions are
enforced by the executor and merge-train.

## States

| State       | Meaning                                      |
|-------------|----------------------------------------------|
| QUEUED      | Ready for an executor to claim                |
| RUNNING     | Claimed by an executor, work in progress      |
| DONE        | Code committed and pushed to agent branch     |
| MERGED      | Branch merged to base by the merge-train      |
| BLOCKED     | Repo path does not exist (only valid reason)  |
| QUARANTINED | Binary hex-only PATCH TEMPLATE stub           |

## Transitions

```
QUEUED → RUNNING     executor claims via CTE with SKIP LOCKED
RUNNING → DONE       code committed + pushed (or push failed, merge-train retries)
RUNNING → BLOCKED    repo path literally missing
RUNNING → QUARANTINED  binary stub with no readable English
DONE → MERGED        merge-train verifies and merges to base branch
RUNNING → QUEUED     zombie release (heartbeat stale >90 min)
```

## Invalid Transitions

- RUNNING → QUEUED for any reason other than zombie release
- Any state → BLOCKED for reasons other than missing repo path
- Skipping a task is never valid — every claim must resolve
