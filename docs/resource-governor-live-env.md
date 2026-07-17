# Resource Governor: Live-Environment Pattern

## Background

Prior to 2026-07-11, `resource_governor.py` froze tuning constants
(`MAX_PARALLEL_CEILING`, `PER_TASK_GB`, `RAM_FLOOR_GB`, etc.) as module-level
constants at import time. This caused fleet divergence: a long-running process
that started before a central config push would silently ignore the new values,
staying clamped at stale defaults.

## Current Design

All capacity thresholds are now read from `os.environ` on every call via
private helper functions (`_ceiling()`, `_disk_soft()`, etc.). This ensures
that tuning pushed by `fleet_control.load_config()` takes effect immediately
without requiring a process restart.

## Implications for New Modules

When adding new governor-style parameters:

- **DO** read from `os.environ.get(...)` inside a function, not at module scope.
- **DO** provide a sensible default so the governor degrades gracefully if the
  env var is unset.
- **AVOID** caching the result in a module-level variable — the whole point is
  to pick up fleet-wide tuning changes live.
