# Executor reliability — shadow measurement, not a routing change

**Status: SHADOW ONLY.** Nothing in this workstream can affect a live claim.
A live routing change is a separate task the operator authorises after reading
the numbers this produces.

## What was asked vs what the data says

The operator asked for triage lanes split by change type (design / api / feature /
project / page). The 48h outcome data says change type is not the variable that
predicts completion. **Executor identity is**, by a wide margin:

| executor class          | tasks | ok  | success |
|-------------------------|------:|----:|--------:|
| cowork executors        |   600 | 416 |  69.3%  |
| Mac.lan (Mac 1)         |   177 |  28 |  15.8%  |
| Mandys-MacBook-Pro (M2) |    46 |   0 |   0.0%  |
| other                   |    27 |  17 |  63.0%  |

A task routed to a cowork executor is roughly **4.4x** more likely to complete
than the same task on Mac 1, and infinitely more likely than on Mac 2. No
plausible split by change type produces a spread anywhere near that. Triaging by
change type while ignoring this optimises the wrong axis.

## Why this is shadow-only and not live

Flipping routing on this evidence would starve the Mac runners of work and
concentrate everything on cowork executors — which may simply be **the least
loaded rather than the most capable**. The current data cannot separate those two
hypotheses. The shadow run is exactly what distinguishes them, so it is not
skippable.

## What was built

`runner/executor_reliability.py`

1. **Backfill** — `backfill_agent_outcomes()` walks historical terminal tasks into
   `agent_outcomes` (app=project, task_slug=slug, role=kind, provider=executor
   class, model=raw account, settlement=terminal state, latency_ms=claim→terminal
   wall clock, metadata.attempts). Idempotent: already-recorded slugs are skipped.
   The table existed in the schema with zero rows; this populates it rather than
   adding another one.
2. **Reputation rollup** — `rollup_reputation()` aggregates into `agent_reputation`
   per `(executor_class, kind)`: success rate, median wall clock, attempts per
   success, sample count. Keyed on **class, not pid** — accounts like
   `Mac.lan-57190` and `cowork-executor-v6-1786033329` are ephemeral, so a
   per-account key makes every row n=1.
3. **Shadow router** — `record_shadow_decision()` writes to `routing_decisions`
   only: which executor actually claimed, which one a reliability-weighted policy
   *would* have chosen, and (via `settle_shadow_decision`) the realised outcome.
   Wired into `runner.py` **after** `db.claim_task()` has already returned, so it
   is structurally incapable of influencing the claim.
4. **Report** — `shadow_report()` renders disagreement rate and the counterfactual
   success rate of the shadow policy's picks.

## Hard requirements, and how each is enforced

- **Sample floor of 20.** `MIN_SAMPLES = 20`. Any `(class, kind)` below it is
  marked `usable=False, evidence="insufficient_evidence"` and `best_executor()`
  returns `(None, "insufficient_evidence")` rather than picking. Routing on n≤2 is
  precisely the defect that put `verify_diff` on a 3B model at quality 4.7 from a
  single observation. Tests
  `test_reputation_below_sample_floor_is_labelled_not_trusted` and
  `test_best_executor_refuses_to_pick_on_thin_evidence` pin this.
- **No write to `tasks.account`, no queue reorder, no admission gate.** The shadow
  path touches `routing_decisions` and nothing else.
  `test_shadow_decision_never_writes_tasks_or_reorders_the_queue` asserts zero
  writes to `tasks`.
- **Fail-soft everywhere.** Every public entry point swallows exceptions;
  `record_shadow_decision` returns `None` on failure.
  `test_shadow_path_exception_never_affects_the_real_claim` pins it.

## Reading the report honestly

The counterfactual figure is an **upper bound, not a promise** — it credits the
shadow policy with every task it would have re-routed, and it still cannot
separate capability from load. `shadow_report()` says so in its own output, and a
test asserts that caveat is present. Below `REPORT_THRESHOLD` (200) decisions the
report refuses to conclude anything at all.

## Running it

```
cd runner && python3 executor_reliability.py      # backfill → rollup → report
cd runner && python3 -m pytest tests/test_executor_reliability.py -q
```

Tests: 17 passing. Full runner suite: 900 passed, 2 skipped, 0 failures.
