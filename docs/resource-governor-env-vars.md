# Resource Governor — Environment Variable Reference

All resource-governor tuning parameters are read **live from `os.environ`** on every
call rather than frozen at import time. This means fleet_control pushes (via the
`fleet_config` table) take effect immediately without restarting the runner process.

| Variable | Default | Description |
|---|---|---|
| `MAX_PARALLEL_CEILING` | `12` | Hard upper bound on concurrent task lanes |
| `PER_TASK_GB` | `2` | Estimated RAM per task for throttle math |
| `RAM_FLOOR_GB` | `4` | Reserved RAM; governor throttles below this |
| `DISK_SOFT_PCT` | `85` | Disk-usage % that triggers gentle pruning |
| `DISK_HARD_PCT` | `95` | Disk-usage % that triggers aggressive pruning + throttle |

## Why live-read matters

Prior to the 2026-07-11 fix, these were module-level constants snapshotted once at
import. A long-running process that started before a central tuning push would silently
diverge — e.g. Mac 2 was clamped to ~4 concurrent tasks against a 16-lane ceiling
because its `PER_TASK_GB` / `RAM_FLOOR_GB` were stale. Reading from env on every call
eliminates this class of drift bug.
