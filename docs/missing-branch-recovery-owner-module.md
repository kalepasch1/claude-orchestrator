# Missing-branch auto-recovery — owner module (fleet-wide)

**Slice 3 deliverable.** Locates the existing owner of fleet-wide missing-branch handling so
later slices insert logic in the right place instead of adding a fourth parallel implementation.
Determined 2026-08-12 against `origin/master` @ `c635b983`.

Contract-tested by `runner/tests/test_missing_branch_owner_contract.py` — if any path or
signature below is renamed, that test fails rather than a later slice silently no-op'ing.

## Answer

| Role | Location |
|---|---|
| **Owner module** | `runner/branch_fleet_recovery.py` |
| **Owner function (per task)** | `recover_branch(task, repo_path, base_branch="master") -> dict` |
| **Fleet batch entry point** | `sweep(project_id=None) -> list[dict]` |
| **Scheduled entry point (every 4h)** | `runner/branch_recovery_periodic.py::run()` |
| **Detection helper** | `runner/branch_detection.py::detect_missing_branches(repo_path, tasks) -> list[dict]` |
| **Standalone diagnostic — NOT in the pipeline** | `runner/missing_branch_audit.py::auto_recover_missing_branches(dry_run=True, max_recover=10)` |

## Insertion point for later slices

**Put new recovery logic in `branch_fleet_recovery.recover_branch`.** It is the only function on
*both* live code paths. Do **not** insert into either `sweep()` — see the hazard below.

`recover_branch` returns `{"recovered": bool, "strategy": str}`; `sweep` adds `"slug"`. Known
strategies: `already_exists`, `fetched_remote`, `dry_run`. Extend that dict rather than changing
its shape — `runner/tests/test_branch_recovery_access.py` asserts on these keys.

## Hazard: three implementations and two `sweep()` functions

There are **three** missing-branch recovery implementations in the tree, and the two most
plausible-looking insertion points are the wrong ones:

1. `branch_fleet_recovery.sweep(project_id=None)` — gated by `ORCH_FLEET_BRANCH_RECOVERY`,
   batched by `ORCH_FLEET_RECOVERY_BATCH` (5). **Has no production caller.** Every reference
   outside its own module is in `runner/tests/test_branch_recovery_access.py`.
2. `branch_recovery_periodic.sweep()` / `run()` — this is what the fleet scheduler actually runs.
   It **reimplements the loop**, calling `branch_fleet_recovery.recover_branch` and
   `_branch_exists_local` directly and bypassing `sweep()` entirely. It is gated by a *different*
   flag (`ORCH_BRANCH_RECOVERY_ENABLED`), a *different* dry-run (`ORCH_BRANCH_RECOVERY_DRY_RUN`,
   default **true**), and a *different* batch size (`ORCH_BRANCH_RECOVERY_BATCH`, 20).
3. `missing_branch_audit.auto_recover_missing_branches` — a third unwired implementation; its own
   docstring says "standalone diagnostic (not part of the periodic pipeline)".

Two same-named `sweep()` functions with different signatures (`sweep(project_id=None)` vs
`sweep()`) sit one import apart. Adding logic to #1 is the natural reading of "fleet-wide
recovery" and would ship code that never executes in production. Adding it to #3 has the same
outcome.

**Consequences to carry forward:**

- `ORCH_FLEET_BRANCH_RECOVERY` and `ORCH_FLEET_RECOVERY_BATCH` do **not** gate the scheduled path.
  Only `ORCH_BRANCH_RECOVERY_*` does. Pushing the former fleet-wide via `fleet_control.py` will
  appear to do nothing.
- The scheduled path defaults to **dry-run true**, so recovery is report-only until
  `ORCH_BRANCH_RECOVERY_DRY_RUN=false` is set. Any slice measuring "did recovery happen" must
  account for this or it will read a working system as broken.
- Whether #1 and #3 should be collapsed into the periodic path is a real question, but it is a
  behavior change to a live scheduled job and belongs in its own task — not in a locate-the-owner
  slice. Recorded here rather than silently performed.

## Search terms that led here

`branch_missing`, `missing_branch`, `oldest_wait_age_s`, `silent_blocker`. The last two appear
only in `diagnostic_missing_branch.py` (a top-level ad-hoc script reading `stats['missing_branch']`
and `stats['oldest_wait_age_s']`); neither is a fleet-wide owner and neither should be extended.
