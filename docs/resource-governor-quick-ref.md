# Resource Governor — Environment Variables Quick Reference

The resource governor reads all tunables from environment variables on every
call (not frozen at import). This ensures fleet-wide config pushes via
`fleet_control.load_config()` take effect immediately without process restart.

| Variable | Default | Purpose |
|---|---|---|
| `MAX_PARALLEL_CEILING` | `12` | Upper bound on concurrent task lanes |
| `PER_TASK_GB` | `2` | RAM headroom reserved per running task |
| `RAM_FLOOR_GB` | `4` | Minimum free RAM before throttling kicks in |
| `DISK_SOFT_PCT` | `85` | Disk usage % that triggers soft throttle |
| `DISK_HARD_PCT` | `95` | Disk usage % that triggers hard prune + throttle |
| `ORCH_EVENT_FILE_SIZE_MB` | `100` | Max size per daily JSONL event file |
| `ORCH_EVENT_BACKUPS_PER_DAY` | `3` | Rotated backups kept per day |

All values are re-read live from `os.environ` on each governor cycle so that
centrally pushed tuning (via `fleet_config` table → `fleet_control.py`) is
picked up without restarting the runner process.
