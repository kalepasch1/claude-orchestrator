# Fleet Config — Safe Key Conventions

## Prefix Rule
All fleet-wide configuration keys MUST be prefixed with `ORCH_` to distinguish
them from project-local or secret-bearing keys.

## Safe vs Unsafe Keys
- **Safe (fleet-pushable):** Feature flags, thresholds, cron intervals, routing
  weights, model preferences — anything that contains no credentials.
- **Unsafe (never fleet-push):** API keys, tokens, passwords, signing secrets,
  database URLs. These stay in per-machine `.env` files or secret managers.

## Propagation
`fleet_control.py` reads the `fleet_config` table and applies safe keys to all
machines via the in-process gateway. Changes take effect on the next heartbeat
cycle without requiring SSH or manual intervention.

## Example Keys
| Key | Type | Description |
|-----|------|-------------|
| `ORCH_ANOMALY_SPIKE` | float | Anomaly spike multiplier threshold |
| `ORCH_CODE_REQUESTS_PER_RUN` | int | Max code requests per self-improvement run |
| `ORCH_AUTO_MERGE_SCOPE` | string | Scope for auto-merge (`nonmaterial`, `docs_only`) |
