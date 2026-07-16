# startup-selfcheck-autoheal — Sub-task Decomposition

The monolithic `startup_selfcheck.py` performs five sequential checks in a
single `run()` call. To make each check independently testable, retriable,
and composable, the build is split into four sub-tasks ordered so that earlier
ones do not depend on later ones.

## Sub-task 1: Firewall audit (no dependencies)

**Scope:** Extract the firewall check (phase 1) into a standalone
`selfcheck_firewall()` function that returns `{ok: bool, healed: bool, detail: str}`.

**Acceptance test:** Unit test with mocked `subscription_guard` that verifies
enforcement is called when `api_keys_present=True` and `api_allowed=False`.

## Sub-task 2: Worktree cleanup (no dependencies)

**Scope:** Extract the worktree GC call (phase 2) into `selfcheck_worktrees()`
returning `{freed: int, detail: str}`.

**Acceptance test:** Unit test with mocked `worktree_gc.run()` returning a
count; verify the count propagates to the health record.

## Sub-task 3: Zombie reclaim + claimable unblock (depends on sub-task 2)

**Scope:** Extract phases 3–4 (zombie sweep + dagfix/unstick) into
`selfcheck_queue_health()` returning `{zombies_cleared, claimable, detail}`.
Worktree cleanup should run first so freed worktrees can unblock merges
before the claimable count is checked.

**Acceptance test:** Mock `db.select` returning stale RUNNING tasks and an
empty claimable set; verify zombies are reclaimed and dagfix is invoked.

## Sub-task 4: Health verdict + reporter (depends on sub-tasks 1–3)

**Scope:** Aggregate the results from sub-tasks 1–3 plus the RAM check
(phase 5) into a single `runner_health` row. This is the orchestration
layer that calls each sub-check and posts the verdict.

**Acceptance test:** Mock all sub-check functions, verify the health row
contains correct status ("ok" vs "degraded") based on combined results.
