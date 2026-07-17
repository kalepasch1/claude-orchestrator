# Task Priority Order

The executor claims tasks in a strict priority order to ensure
critical fixes land before speculative improvements.

## Priority tiers (highest first)

1. **recovery** — restore broken functionality
2. **toolchain-repair** — fix build or CI infrastructure
3. **bugfix** — targeted defect fixes
4. **build** — new feature implementation
5. **canary** — routing-confidence probes
6. **everything else** — improvements, refactors, docs

Within a tier, tasks are sorted by confidence (descending), then
attempt count (ascending, favouring fresh tasks), then ID.
