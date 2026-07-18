# Security: resource_governor.can_claim() input validation

**Date:** 2026-07-18
**Risk:** Low

## Finding
`can_claim(n_active)` does not validate its parameter. A negative `n_active`
would reduce the RAM headroom requirement, potentially allowing claims under
memory pressure. The parameter is currently always called with a valid count
from runner.py, but defensive validation prevents future misuse.

## Recommendation
Guard with `n_active = max(0, int(n_active or 0))` at function entry,
consistent with the codebase's fail-soft convention.
