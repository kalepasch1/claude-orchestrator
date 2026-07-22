# Zombie Release Protocol

Tasks stuck in `RUNNING` state due to crashed or rate-limited executor sessions
are called "zombies." The fleet automatically detects and releases them.

## Detection Criteria

A task is considered a zombie when all of the following are true:

1. `state = 'RUNNING'`
2. `updated_at` is older than 90 minutes
3. `account` matches a known executor prefix (e.g., `cowork-executor%`)

## Release Mechanism

The executor's Step 0b runs this SQL at the start of every session:

```sql
UPDATE tasks SET state='QUEUED', note='zombie released — heartbeat stale >90min'
WHERE state='RUNNING'
  AND updated_at < now() - interval '90 minutes'
  AND account LIKE 'cowork-executor%';
```

## Prevention

Active executors heartbeat their claimed tasks in Step 3g by updating
`updated_at=now()` on all their RUNNING tasks after each task completion.
This keeps the 90-minute window from expiring mid-batch.

## Edge Cases

- If an executor crashes mid-commit, the worktree may contain partial work.
  The next executor should inspect existing branch artifacts before re-implementing.
- Zombies from non-executor accounts (e.g., manual runs) are not auto-released.
