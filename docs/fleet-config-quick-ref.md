# Fleet Config Quick Reference

Lookup table for the most-used `fleet_config` keys and their safe defaults.

## Core Runtime Keys

| Key | Type | Default | Purpose |
|-----|------|---------|---------|
| `ORCH_AUTO_PULL` | bool | `true` | Self-update runtime checkout on each loop |
| `ORCH_TDD_ENABLED` | bool | `false` | Master TDD-gating switch |
| `ORCH_TDD_TASK_KINDS` | CSV | `feature,new-module` | Task kinds requiring TDD |
| `MAX_PARALLEL` | int | `3` | Concurrent task slots per machine |

## Safety Rules

- Keys containing `KEY`, `SECRET`, `TOKEN`, or `PASSWORD` are rejected by `fleet_control.py`.
- All safe keys are prefixed with `ORCH_` or are in the allowlist (`MAX_PARALLEL`, etc.).
- Changes propagate fleet-wide within ~30 s (config cache TTL).

## Common Operations

```sql
-- Read current config
SELECT key, value::text FROM fleet_config ORDER BY key;

-- Set a key
INSERT INTO fleet_config (key, value) VALUES ('ORCH_TDD_ENABLED', 'true')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

-- Check executor heartbeat
SELECT value::text FROM fleet_config WHERE key = 'COWORK_EXECUTOR_V6_LAST_RUN';
```

See `docs/tdd-config.md` for full TDD configuration details and
`docs/RUNTIME-LOCATION.md` for runtime path conventions.
