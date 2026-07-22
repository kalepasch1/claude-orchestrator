# Throttle File Format

The resource governor writes an effective `MAX_PARALLEL` value to
`~/.claude-orchestrator/throttle`. The runner reads this file each loop
to adjust concurrency in real time.

## Format

The file contains a single integer on one line — the current effective
maximum number of parallel task lanes. Example:

```
8
```

## Lifecycle

- **Created** by `resource_governor.py` when disk or RAM pressure changes.
- **Read** by `runner.py` at the top of each scheduling loop.
- **Deleted** is safe — the runner falls back to `MAX_PARALLEL_CEILING` from env.
- **Staleness** — the governor overwrites atomically; partial reads are not possible.
