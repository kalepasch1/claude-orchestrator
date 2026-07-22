# Environment Variable Hygiene

All tunable parameters use environment variables with sensible defaults.
This document lists the conventions enforced across the fleet.

## Naming

- Fleet-wide config keys are prefixed with `ORCH_` (e.g. `ORCH_AUTO_PULL`).
- Secret-bearing keys (API tokens, DB credentials) are **never** pushed via
  `fleet_config`; they live only in `~/.claude-orchestrator/.env` (mode 0600).

## Required on every machine

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | Project API endpoint |
| `SUPABASE_SERVICE_ROLE_KEY` | Service-role key for DB access |
| `ANTHROPIC_API_KEY` | Claude API access |

## Optional / fleet-pushed

| Variable | Default | Purpose |
|---|---|---|
| `ORCH_AUTO_PULL` | `1` | Auto-pull latest code on runner start |
| `ORCH_HEARTBEAT_INTERVAL` | `300` | Seconds between heartbeat pings |
| `KILL_SWITCHES` | _(empty)_ | Comma-separated job names to disable |

## Safety rules

1. Never commit `.env` files — `.gitignore` must include `.env*`.
2. Never log secret values; mask them in diagnostics output.
3. Use `fleet_control.py` for non-secret config propagation.
