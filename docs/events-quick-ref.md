# Events Module — Quick Reference

## Purpose
`runner/events.py` provides a structured JSONL event stream for all significant
runner state transitions (sentinel decisions, merge outcomes, task claims,
governor decisions, deployments).

## Key Functions

| Function | Role |
|---|---|
| `emit(kind, **fields)` | Append a timestamped event; handles rotation/size-capping |
| `read_events(date=None)` | Read all events from a specific date (default: today) |
| `read_recent(limit=100)` | Read the last N events across all dates |

## Storage
Events are written to `.runtime/events/<date>.jsonl`. File rotation triggers
when a single day's file exceeds `ORCH_EVENT_FILE_SIZE_MB` (default: 100 MB),
with up to `ORCH_EVENT_BACKUPS_PER_DAY` (default: 3) rotated backups retained.

## Thread Safety
All writes go through a module-level `threading.Lock`, making `emit()` safe to
call from concurrent task threads without external synchronization.
