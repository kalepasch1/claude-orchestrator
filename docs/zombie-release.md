# Zombie Release Mechanism

When a cowork-executor session crashes or is rate-limited, its claimed tasks
remain in `RUNNING` state indefinitely. The zombie-release step at the top of
each executor loop detects and recovers these orphaned claims.

## Detection criteria

A task is considered a zombie when ALL of the following are true:

- `state = 'RUNNING'`
- `updated_at` is older than 90 minutes (no heartbeat)
- `account LIKE 'cowork-executor%'` (owned by an executor, not a human)

## Recovery action

Zombies are atomically set back to `state = 'QUEUED'` so the next executor
loop can re-claim and complete them. The `note` field records the release
reason for post-mortem analysis.

## Why 90 minutes?

A healthy executor heartbeats every task batch (~5 minutes). 90 minutes
allows for slow tasks, retries, and transient network issues without
prematurely releasing work that is still in progress.
