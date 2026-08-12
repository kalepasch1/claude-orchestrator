# Pinned express lane — why it kept failing, and what the fix changes

Recovery of `backlog-batch-beethoven-a86bb21-recover-pinned-express-lane-diagnose-root-cause`.
Slice 1 fixed the capacity arithmetic and the `_task()` signature; slice 2 (this one)
closes the remaining two red tests. The task asked for the explanation as well as the
change, so both are here.

## Summary

The pinned express lane had **four independent defects**, three of them in the test
harness rather than in the lane itself. That distribution is the interesting part: the
production ordering logic was mostly right, and the reason nobody could tell was that
the tests which would have said so had never run.

| # | Defect | Where | Effect |
|---|---|---|---|
| 1 | capacity computed against a lane count that did not exist | `runner/express_lane.py` | a "15%" reservation took 50% of the machine |
| 2 | `_task()` conflated task id and slug | `runner/tests/test_pinned_express_lane.py` | 11 tests raised `TypeError` at collection |
| 3 | rank-ordering test re-claimed a static list | same file | asserted ordering while proving nothing |
| 4 | multi-project tests declared no projects (and no pause) | same file | queue emptied by host affinity; one test passed for the wrong reason |

## 1. Capacity against a phantom lane count *(slice 1)*

`_total_lanes` was a module constant of **40**, with a `set_total_lanes()` that was
meant to update it — and a repo-wide grep found no caller. The machine's real limit is
`MAX_PARALLEL` (`runner/runner.py:192`, default 12, tuned per machine in `runner/.env`).

So on a stock box:

```
express_lane_capacity() = max(1, int(40 * 0.15)) = 6      # of 12 real lanes → 50%
standard_lane_capacity() = 40 - 6 = 34                    # of a 12-lane machine
```

`ORCH_EXPRESS_LANE_CAPACITY_PCT=15` reserved half the machine and reported a standard
capacity that exceeded the machine. **Fix:** `total_lanes()` reads `MAX_PARALLEL` live —
live rather than cached for the same reason `runner.py` re-checks `eff_limit` every
dispatch loop, since a boot-time snapshot pins the machine to whatever the value was at
boot. Express is also never allowed to take the last lane: a reservation that leaves no
standard lane is a deadlock, not a priority.

## 2. `_task()` conflated id and slug *(slice 1)*

The helper's only positional parameter was named `slug` and was assigned to **both**
`id` and `slug`. Eleven callers want them different — precisely the ones that exercise
lane ordering against `recover-*`, `qafix-*`, `canary-*`, `improve-*` and `relfix-*`
slugs:

```python
_task("recover-1", slug="recover-missing-branch-1", created_at=...)
# TypeError: _task() got multiple values for argument 'slug'
```

A `TypeError` inside a test method is a test *error*, not a collection error, so the
suite still reported a pass count and the eleven failures blended into a long red list
that predated them. **Fix:** first positional is `task_id`; `slug` defaults to it.

## 3. Ordering asserted against a queue that never drains *(slice 1)*

```python
for _ in range(3):
    claimed.append(self._claim(tasks))     # same static list every time
assert claimed == ["pin-1", "pin-2", "pin-3"]
```

A real claim flips the row to `RUNNING`, so it leaves the queue. Re-claiming an
unchanged list returns rank 1 three times, which is what it did: `['pin-1', 'pin-1',
'pin-1']`. **Fix:** drop the claimed id between iterations. The assertion now tests
ordering instead of testing that rank 1 sorts first, thrice.

## 4. Undeclared projects, and a pause nobody declared *(this slice)*

`db.claim_task` derives **host affinity** from the projects table: it builds
`local_repo_pids` from project rows and drops any task whose `project_id` is not in it.
`_make_select` defaults to a single project `p1`, but four tests use `p-priority-1`,
`p-priority-9`, `p-paused`, `p-active` — none declared. Every such task was filtered
out before any sorting ran, and the runner logged:

```
[claim] no locally-runnable tasks: 2 queued, but no project repo is present on
Kales-MacBook-Pro.local (host affinity). Idle until a runnable repo exists.
```

That message names host affinity, so the failure reads as a machine problem. It is a
missing fixture. Two tests also passed `projects=` to a `_claim()` that did not accept
the keyword (`TypeError`), which is what the fixture would have been for.

**Fix:** `_claim()` accepts and forwards `projects`, defaulting to `_projects_for()`,
which declares a row for every `project_id` the queued tasks reference.
`repo_path=None` is deliberate — `db.repo_runnable_here(None)` returns `True`, so
affinity is satisfied without touching the filesystem.

### The one that was passing for the wrong reason

`test_paused_project_filtering_happens_before_express_lane` asserted that a pinned task
in a paused project is not claimed — while supplying **no `controls` rows at all**.
Nothing in the fixture ever said `p-paused` was paused. It passed only because the
missing projects fixture was emptying the whole queue, and it flipped to a genuine
failure the instant defect 4 was fixed:

```
AssertionError: 'pinned-paused-proj' != 'unpinned-active'
```

That is the correct answer to the question the fixture actually asked. **Fix:** state
the pause. `claim_task` reads `controls(scope='project', paused=true)` and maps by
project *name*, so the test now supplies that row — and two new cases pin the rest of
the rule: a `remote-quarantine` pause is ignored, and a pause beats the pin even when
the paused task is the only thing queued.

## What this does not fix

The lane accounting API — `assign_task_lane()`, `release_lane()`,
`should_use_express_lane()` — is still not called from the runner's lease lifecycle.
`db.py` wires only the *ordering* half, deliberately and with a comment saying so
("express work goes first — with no lane accounting to leak"). Capacity is now correct
whenever that half is wired; wiring it is a separate change with its own lifecycle
risk, and inventing it inside a test-recovery slice would be the tumour-growth this
repo's transplant discipline exists to prevent.

## Verification

```
python3 -m pytest runner/tests/test_pinned_express_lane.py \
                 runner/tests/test_express_lane_capacity.py \
                 runner/tests/test_express_lane_wiring.py \
                 runner/tests/test_fleet_express_lane.py -q
102 passed
```

Before slice 1: 11 failures. After slice 1: 2. After this slice: 0.
