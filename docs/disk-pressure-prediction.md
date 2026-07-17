# Disk-Pressure Prediction

`resource_governor.py` includes a predictive pruning mode that fits a linear
trend to recent `resource_events` disk-usage values. If the projected usage
would breach `DISK_HARD_PCT` within approximately 2 hours, the governor
triggers proactive pruning and throttles concurrency *before* the disk fills.

## Pruning priority (descending)

1. Merged git worktrees (safe — work already landed)
2. Stale `.runtime/logs/` older than 7 days
3. Build caches (`node_modules`, Docker layers — behind opt-in flags)
4. Dangling twin worktrees from crashed executors

## Throttle behaviour

When predictive pruning fires, the governor writes a reduced `MAX_PARALLEL`
to the throttle file. Once disk usage falls below `DISK_SOFT_PCT`, the
governor gradually restores concurrency back toward `MAX_PARALLEL_CEILING`.
