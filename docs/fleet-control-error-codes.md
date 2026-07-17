# Fleet Control Error Codes

Quick reference for error states returned by `fleet_control.py` operations.

| Code | Meaning | Recovery |
|------|---------|----------|
| `CONFIG_KEY_INVALID` | Key not prefixed with `ORCH_` or contains secrets | Use `ORCH_` prefix; store secrets in `.env` only |
| `PUSH_REJECTED` | Git push to fleet machines failed | Check SSH connectivity; retry via `fleet_control.self_update()` |
| `STALE_HEARTBEAT` | Machine heartbeat older than 90 min | Machine may be offline; check launchd status |
| `DB_QUERY_FAIL` | Supabase query returned error | Fail-soft: operation continues; check Supabase dashboard |
| `LOCK_CONTENTION` | Runner lock held by another process | Normal during concurrent runs; wait or check `runner.lock` |

## Notes

- All errors are fail-soft by convention — they log but do not crash the runner.
- Config keys without the `ORCH_` prefix are local-only and not propagated fleet-wide.
- See `RUNTIME-LOCATION.md` for runtime path conventions.
