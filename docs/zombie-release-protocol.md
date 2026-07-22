# Zombie Release Protocol

When an executor session crashes, is rate-limited, or times out, its claimed
tasks remain in `RUNNING` state with a stale `updated_at` timestamp. These
"zombie" tasks block queue throughput until released.

## Detection

Every executor loop iteration runs a zombie-release query before claiming
new work:

```sql
UPDATE tasks SET state='QUEUED', note='zombie released — heartbeat stale >90min'
WHERE state='RUNNING'
  AND updated_at < now() - interval '90 minutes'
  AND account LIKE 'cowork-executor%';
```

## Why 90 minutes?

- Typical task implementation takes 2–15 minutes.
- The longest observed legitimate task run is ~60 minutes (large build tasks).
- 90 minutes provides a safety margin above the longest legitimate run while
  still recovering zombies within a reasonable window.

## Heartbeat mechanism

While processing a batch, executors update `updated_at=now()` on all their
remaining claimed tasks after each task completion. This keeps alive tasks
from being mistakenly released while the executor is still active.

## Related

- `fleet_control.py` — fleet-wide config propagation
- `runner.py` — primary task loop with periodic heartbeat
- `scoreboard.py` — tracks zombie-release events in merge-rate metrics
