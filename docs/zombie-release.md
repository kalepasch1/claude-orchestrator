# Zombie Release Protocol

Tasks stuck in RUNNING state beyond the heartbeat window (90 minutes)
are automatically released back to QUEUED by the executor's zombie-release
step. This prevents crashed or rate-limited sessions from permanently
blocking work items.

## Trigger conditions

- Task state is RUNNING
- `updated_at` is older than 90 minutes
- Account matches the `cowork-executor%` pattern

## Behaviour

The task's state reverts to QUEUED with a note explaining the release.
The next executor loop picks it up normally. Attempt count is preserved
so the system can track repeated failures.
