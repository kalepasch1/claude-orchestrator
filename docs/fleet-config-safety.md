# Fleet Config Safety Rules

`fleet_control.py` applies central `fleet_config` rows into the runner's
environment on every loop iteration, but only keys that pass a two-stage
safety gate:

## Deny list (checked first)

Any key whose uppercased name contains one of these markers is **always
rejected**, regardless of prefix:

`KEY`, `SECRET`, `TOKEN`, `PASSWORD`, `PWD`, `CREDENTIAL`

## Allow-list prefixes

After passing the deny check, the key must start with one of:

`ORCH_`, `MAX_PARALLEL`, `PER_TASK_GB`, `RAM_FLOOR_GB`, `RAM_`,
`RELEASE_`, `QUEUE_`, `CONT_`, `JANITOR_`, `REMEDIATION_`,
`DEFAULT_TEST_CMD`, `TASK_TIMEOUT`, `ENABLE_`, `SESSION_`,
`ACCOUNT_COOLDOWN`, `MERGE_`, `DEPLOY_`, `INTEGRATE_`, `COST_`

Keys that match neither are silently ignored.

## Implications

- Secrets (API keys, PATs, tokens) can safely live in `fleet_config`
  for executor retrieval without risk of being injected into runner env.
- New config knobs must use an approved prefix or be added to `_SAFE_PREFIXES`.
- The gate is fail-soft: any DB error during `load_config()` is swallowed
  so the runner continues with its existing env.
