# Resource Governor — Quick Reference

## Purpose
`runner/resource_governor.py` protects the host Mac from resource exhaustion
during parallel task execution. It monitors disk and RAM, throttles concurrency,
and prunes stale worktrees.

## Key Functions

| Function | Role |
|---|---|
| `can_claim(n_active)` | Pre-task gate — returns `(ok, reason)` before each new task starts |
| `govern()` | Periodic sweep — prunes worktrees, adjusts throttle, emits events |
| `prune()` | Removes merged/stale worktrees and dangling branches |
| `set_throttle(n)` | Writes effective MAX_PARALLEL to the control file |
| `current_limit()` | Reads the current throttle value |
| `dashboard_gauge()` | Returns a dict for the fleet-admin dashboard |

## Configuration (env vars, live-reloaded each call)

| Var | Default | Meaning |
|---|---|---|
| `MAX_PARALLEL_CEILING` | 12 | Upper bound on concurrent tasks |
| `DISK_SOFT_PCT` | 80 | Prune above this disk usage % |
| `DISK_HARD_PCT` | 90 | Throttle to 1 lane + alert |
| `RAM_HARD_PCT` | 82 | RAM pressure ceiling |
| `RAM_FLOOR_GB` | 4.0 | Minimum free RAM before blocking |
| `PER_TASK_GB` | 1.5 | RAM headroom required per new task |

## Design Notes
- All thresholds are read from `os.environ` on every call (not frozen at import)
  to support live fleet-wide tuning via `fleet_control.py`.
- Predictive disk trending fits a linear model to recent `resource_events` rows
  and pre-emptively prunes/throttles before hitting `DISK_HARD`.
- Worktree pruning checks: uncommitted changes, unmerged branches, recent
  activity, and origin push status before removing.
- `pressure_should_block()` uses two-signal corroboration: kernel memory
  pressure AND low measured headroom must BOTH be true before blocking new
  tasks. This prevents stale `/proc/pressure` signals (which can linger after
  a transient spike) from collapsing fleet concurrency on their own.
