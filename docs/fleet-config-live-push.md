# Fleet Config Live-Push Mechanism

The `fleet_config` Supabase table stores key-value pairs that control fleet-wide
tuning. `fleet_control.py` reads this table each runner loop and injects values
into `os.environ`, making them available to all modules without restart.

## Safe key prefix

All fleet-pushable keys use the `ORCH_` prefix (e.g. `ORCH_EVENT_FILE_SIZE_MB`).
Keys without this prefix are local-only and not overwritten by the gateway.

## Push flow

1. Operator inserts/updates a row in `fleet_config` (via SQL or admin UI).
2. Each machine's runner calls `fleet_control.load_config()` at loop top.
3. `load_config()` sets matching env vars; downstream modules read them live.
4. No restart required — the next loop iteration picks up the change.

## Restrictions

- Keys containing secrets or credentials must **not** be pushed fleet-wide.
- Only keys in the safe-list are applied; unknown keys are logged and skipped.
