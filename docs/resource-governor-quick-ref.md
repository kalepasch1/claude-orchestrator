# Resource Governor — Quick Reference

## Overview
`runner/resource_governor.py` monitors disk and RAM pressure on fleet Macs
and dynamically throttles task concurrency to keep machines healthy.

## Key Thresholds (all read live from env via fleet_control)

| Env Var               | Default | Effect                                      |
|-----------------------|---------|---------------------------------------------|
| MAX_PARALLEL_CEILING  | 12      | Hard cap on concurrent tasks                |
| DISK_SOFT_PCT         | 80      | Triggers automatic pruning                  |
| DISK_HARD_PCT         | 90      | Throttles to 1 task + emits alert           |
| RAM_HARD_PCT          | 82      | Aggressive throttling engages               |
| RAM_FLOOR_GB          | 2.0     | Pauses all new claims below this free RAM   |
| PER_TASK_GB           | 0.15    | Reserved headroom per concurrent task       |

## Why Live Reads Matter
All thresholds are read from `os.environ` on every call (not frozen at import).
This ensures `fleet_control.load_config()` pushes take effect without restarting
the runner process. See the 2026-07-11 comment block in resource_governor.py for
the root-cause analysis of the Mac 2 stale-ceiling incident.

## Pruning Opt-Ins

| Env Var             | Default | What it prunes                  |
|---------------------|---------|----------------------------------|
| LOG_KEEP_DAYS       | 7       | Logs older than N days           |
| PRUNE_NODE_MODULES  | false   | node_modules in worktrees        |
| PRUNE_DOCKER        | false   | Dangling Docker images           |
| PRUNE_LIB_CACHES    | false   | ~/Library/Caches                 |
