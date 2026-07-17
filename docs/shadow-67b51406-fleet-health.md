# Fleet Health Check Improvement — Zombie Detection

## Current Behavior

The cowork executor releases zombies via a SQL update on tasks with
`updated_at < now() - interval '90 minutes'` and `account LIKE 'cowork-executor%'`.

## Gap

Tasks claimed by non-cowork accounts (e.g. `runner-*`, `shadow-*`) are not
covered by the zombie release query. If a runner crashes, its tasks remain
RUNNING indefinitely.

## Recommended Fix

Broaden the zombie release to cover all executor accounts, or add a
separate sweep for runner-claimed tasks:

```sql
UPDATE tasks SET state='QUEUED', note='zombie released — heartbeat stale'
WHERE state='RUNNING'
  AND updated_at < now() - interval '120 minutes';
```

This would be a safe addition to the fleet heartbeat cron without
affecting active executors (which heartbeat every few minutes).
