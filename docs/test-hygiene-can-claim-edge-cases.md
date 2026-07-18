# Test Hygiene: can_claim() edge case coverage

**Date:** 2026-07-18
**Category:** Test hygiene

## Suggested test cases for resource_governor.can_claim()

These edge cases are not currently covered and would improve confidence:

1. **n_active=0** (cold start) — should always return (True, "ok") when
   RAM and disk are healthy
2. **RAM exactly at floor + per_task** — boundary condition, should return
   False
3. **Disk at exactly DISK_HARD** — boundary condition, should return False
4. **Both RAM and disk failing** — should report RAM reason (checked first)
5. **psutil unavailable** — should fall back to vm_stat gracefully
6. **Negative n_active** — should be treated as 0 (defensive)

## Testing approach
Use monkeypatching to control `ram_free_gb()`, `disk_pct()`, and
`mem_pressure_ok()` return values, keeping tests deterministic and
independent of actual system state.
