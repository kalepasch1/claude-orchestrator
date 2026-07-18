# Security Checklist

Pre-merge security checks for the orchestrator codebase.

## Secrets handling

- No hardcoded secrets or credentials in source files
- All secrets loaded via environment variables or fleet_config
- Config keys prefixed with ORCH_ for fleet-wide distribution
- fleet_config only stores non-sensitive configuration values

## Authentication

- GitHub PAT used for git operations only (never logged)
- API keys rotated periodically via fleet_config updates
- No secrets passed as command-line arguments (visible in process list)

## Database

- No DROP TABLE or TRUNCATE without WHERE on production tables
- SQL queries parameterized (no string interpolation)
- fleet_config writes restricted to safe config keys

## Code execution

- Fail-soft error handling: errors don't wedge the runner
- Resource governor gates pool expansion on memory checks
- Thread-safe singleton pattern with explicit locks
