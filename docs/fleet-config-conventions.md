# Fleet Configuration Conventions

Rules for managing fleet-wide configuration via `fleet_control.py`.

## Key naming

All fleet-wide config keys must be prefixed with `ORCH_` to distinguish
them from local-only settings.

```
ORCH_MAX_CONCURRENCY=8
ORCH_COOLDOWN_SECONDS=30
ORCH_CANARY_ENABLED=true
```

## Safe vs unsafe keys

**Safe (pushable fleet-wide):**
- Tuning parameters (concurrency, cooldowns, thresholds)
- Feature flags (canary enable/disable)
- Logging levels

**Unsafe (never push fleet-wide):**
- API keys, tokens, secrets
- Database credentials
- Signing keys (`AGENT_SIGNING_SECRET`)

## Propagation

Config changes go through the central `fleet_config` table and are
applied via `fleet_control.py`'s in-process gateway. Do not use manual
SSH or second-terminal steps.
