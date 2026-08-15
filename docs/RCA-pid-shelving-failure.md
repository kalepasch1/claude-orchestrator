# RCA — "shelved by queue-velocity PID (low EV, integral too high)"

Task: `backlog-batch-beethoven-ccacb00-fix-tests-diagnose-pid-shelving-failure`
Base: `master` @ `64a7b0ef`

## 1. Exact location of the string

The message is not an exception and not a CI warning. It is a literal written into the
`tasks.note` column:

```
runner/queue_velocity.py:213
    db.update("tasks", {"id": t["id"]},
              {"state": "SHELVED",
               "note": f"shelved by queue-velocity PID (low EV, integral too high)"})
```

It is written by `_shelve_lowest_ev()` (`runner/queue_velocity.py:171`), which is called
from two places in `run()`:

| Action | Line | Trigger |
| --- | --- | --- |
| D (derivative) | ~297 | `acceleration > 0 and consecutive_positive >= 2 and depth > 200` |
| I (integral) | ~316 | `shelve_pressure >= SHELVE_CONSECUTIVE_REQUIRED` |

The note text names the I-action, so a task carrying it was shelved because the
cumulative-surplus term crossed `INTEGRAL_SHELVE_THRESHOLD` (default 5000) and stayed
over it for `SHELVE_CONSECUTIVE_REQUIRED` (default 2) consecutive samples.

## 2. Classification

**Test assertion failure.** Not a runtime exception, not a CI/CD warning.

`python3 -m pytest runner/tests/test_branch_velocity_recovery.py` failed 4 of 21:

```
FAILED SingleLowEvSampleNotShelvedTest::test_consecutive_over_threshold_samples_do_shelve
FAILED SingleLowEvSampleNotShelvedTest::test_single_over_threshold_sample_builds_pressure_only
FAILED IntegralClampTest::test_integral_below_max_is_not_flagged
FAILED IntegralClampTest::test_integral_is_clamped_at_max
```

with, e.g.:

```
    self.assertEqual(results[-1]["integral"], 150)
E   AssertionError: 0 != 150
```

Every failure is the same symptom: **the integral stayed at 0** when the fixture expected
it to accumulate.

## 3. Root cause

The controller integrates on *effective* depth, not raw depth
(`runner/queue_velocity.py:248-250`):

```python
pinned_depth = _pinned_depth()
effective_depth = max(0, depth - pinned_depth)
```

Pinned work is express-lane work the operator has explicitly prioritised. It is not
backlog, so excluding it from the integral is correct and deliberate — the in-file comment
records the incident it fixed: a pinned burst spiked depth, the integral crossed the
threshold, and the I-action then shelved queued work *including the pinned items
themselves*.

`_queue_depth()` and `_pinned_depth()` both call `db.count("tasks", …)`, differing only
in the `pinned` filter:

```python
def _queue_depth():   return db.count("tasks", {"state": "eq.QUEUED"})
def _pinned_depth():  return db.count("tasks", {"state": "eq.QUEUED", "pinned": "is.true"})
```

The test harness stubbed both with **one blanket value**:

```python
with patch.object(qv.db, "count", return_value=d):
    results.append(qv.run())
```

So for every sample the harness asserted `depth == d` **and** `pinned == d`, giving
`effective_depth = max(0, d - d) = 0` on every window. `effective_velocity` is therefore
always 0, and the integral update

```python
if effective_velocity > 0:
    integral += effective_velocity
else:
    integral = max(0, integral + effective_velocity)
```

never leaves 0. Visible directly in the captured stdout of the failing run:

```
[queue-velocity] depth=400 (pinned=400 effective=0) velocity=+100 eff_velocity=+0
                 accel=+0 integral=0 consecutive_positive=3 shelve_pressure=0
```

`depth=400`, `pinned=400`, `effective=0` — a queue in which every single queued task is
pinned, which is not a state the fixture ever meant to describe.

**The production controller is correct. The test double was stale**: it predates the
pinned-exclusion change and was never updated to distinguish the two counts. So the answer
to "why did the integral become too high under the test conditions" is that it did not —
it became *stuck at zero*, and the four assertions that expected accumulation failed.

## 4. Fix

`runner/tests/test_branch_velocity_recovery.py` only. **No production logic changed.**

- `ControllerTestBase._count_stub(depth, pinned)` answers `db.count` per query rather than
  with a blanket value, discriminating on the `pinned=is.true` filter, and clamps
  `pinned` to `depth` (pinned queued tasks are a subset of queued tasks; a fixture
  reporting more pinned than queued describes a queue that cannot exist).
- `run_with_depths(depths, pinned=0, **overrides)` now takes an explicit `pinned` count,
  defaulting to 0 so each sample drives the controller exactly as the test name says.

Result: `21 passed` (was `4 failed, 17 passed`).

Added `PinnedExcludedFromIntegralTest` (5 tests) so the behaviour and the fixture's
ability to express it are both pinned:

- growth made entirely of pinned work does not build the integral
- growth in ordinary work does build the integral
- a pinned burst never triggers the I-action (the D-action still fires on raw
  acceleration — intended, and asserted so the distinction is not lost)
- raw depth/velocity are still what the P-action and logs report
- an unavailable pinned count is fail-soft and degrades to the old behaviour

Final: `26 passed`.

## 5. Operational reading of the note

A task in production carrying this note was shelved because sustained NON-pinned queue
growth pushed the integral past `ORCH_QV_INTEGRAL_SHELVE`, and it sat in the lowest-EV
slice (`ORCH_QV_SHELVE_PCT`, default 20%, ordered `confidence.asc.nullsfirst`). Before
shelving, `_recovery_action()` runs a zero-spend branch check — a task whose branch exists
or is mechanically reconstructable keeps its slot, and infra errors during the check are
fail-soft (not shelved). So the note means: real backlog pressure, low confidence, and no
recoverable branch. Shelved tasks are recoverable via `auto_remediate.recover_shelved`.

Relevant knobs: `ORCH_QV_INTEGRAL_SHELVE` (5000), `ORCH_QV_SHELVE_CONSECUTIVE` (2),
`ORCH_QV_INTEGRAL_MAX` (15000), `ORCH_QV_SHELVE_PCT` (0.20),
`ORCH_QV_SHELVE_MIN_DEPTH` (500).

## 6. Out of scope — separate pre-existing failure

`runner/tests/test_ev_low_ev_early_exit.py` fails 39 tests, all
`AttributeError: module 'ev_scheduler' has no attribute 'should_enqueue' /
'task_ev' / 'shelve_low_ev' / 'filter_enqueueable'`. That is a missing implementation in
`runner/ev_scheduler.py`, not a PID-shelving defect, and it is unchanged by this task.
Recorded here so it is not rediscovered as a regression from this work.
