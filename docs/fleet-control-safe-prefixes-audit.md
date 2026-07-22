# Fleet Control: safe config prefix audit

**Date:** 2026-07-18
**Category:** Mechanical / documentation

## Summary
`fleet_control.py` uses `_SAFE_PREFIXES` and `_DENY_MARKERS` to gate which
config keys can be pushed fleet-wide. This audit confirms the current lists
are consistent with the codebase's usage:

### Safe prefixes verified
All `ORCH_*`, `MAX_PARALLEL*`, `PER_TASK_GB`, `RAM_*`, `RELEASE_*`, `QUEUE_*`,
`DEPLOY_*`, `MERGE_*` prefixes are used by `resource_governor.py`, `runner.py`,
and `merge_train.py` respectively.

### Deny markers verified
`KEY`, `SECRET`, `TOKEN`, `PASSWORD`, `PWD`, `CREDENTIAL`, `PAT` — all block
any config key containing these substrings, preventing accidental credential
leakage through the fleet_config broadcast channel.

### No gaps found
Current prefix/deny lists are complete for the existing codebase.
