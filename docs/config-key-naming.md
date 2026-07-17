# Fleet Config Key Naming Convention

All fleet-wide configuration keys stored in `fleet_config` follow these rules:

- **Prefix with `ORCH_`** to distinguish fleet config from local env vars
- **Use SCREAMING_SNAKE_CASE** for consistency with environment variable conventions
- **No secrets or credentials** in fleet config — secrets go in `.env` files only
- **Boolean values**: use string `"true"` / `"false"` (stored as jsonb text)
- **JSON values**: store as proper jsonb objects for structured data

Examples: `ORCH_TDD_ENABLED`, `ORCH_AUTO_PULL`, `ORCH_SPEND_CAP_USD`
