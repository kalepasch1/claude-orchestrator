# Sentinel regression alarms — dedupe storms and ram-clamp thrash become tasks, not log noise

## Problem (from 2026-07-10 fleet brief)
Two issue classes burned operator time because they only surfaced as raw sentinel log
lines the operator had to notice and diagnose manually:
1. Dedupe storm: 45 `dedupe quarantined N duplicate QUEUED rows` events/24h. Root cause
   (task_slicer re-slicing) is fixed in commit 0ed9cf5, but the next duplicate-producing
   enqueuer will again be visible only as log noise.
2. Ram-clamp thrash: 110 clamp events/24h unloading the same models in a loop. Mitigated
   by ORCH_OLLAMA_NUM_CTX cap + slot admission wait (commit dcfc39b), but a regression
   would again be silent.

## Objective
Extend `runner/sentinel.py` (or a small `runner/sentinel_alarms.py` it calls) so sentinel
self-diagnoses these classes and files actionable work autonomously:
1. Maintain rolling 6h counters (persisted under `.runtime/`) for `dedupe` quarantine
   totals and `ram-clamp` events.
2. When dedupe quarantines exceed a threshold (env `ORCH_ALARM_DEDUPE_6H`, default 20):
   group the quarantined rows by slug prefix and parent note to identify the likely
   producer, then enqueue ONE diagnostic task (canonical intake format) titled
   `qafix-duplicate-enqueuer-<producer>` carrying the grouped evidence, and open one
   approval card only if the producer can't be inferred.
3. When ram-clamp events exceed a threshold (env `ORCH_ALARM_RAMCLAMP_6H`, default 15):
   enqueue ONE task `qafix-memory-pressure-<host>` with the clamp lines, loaded-model
   sizes, and current ORCH_OLLAMA_* config attached.
4. Dedupe the alarms themselves: one open task per class per host at a time (check for an
   existing QUEUED/RUNNING slug before inserting — use the idempotent pattern from
   task_slicer._slice_exists).

## Constraints
- Fail-soft: alarm code must never wedge the sentinel loop; swallow and log errors.
- All thresholds env-tunable via ORCH_-prefixed fleet_config keys; no secrets.
- Unit tests for: counter rollover, threshold trip, producer grouping, alarm dedupe,
  disabled-by-env, and sentinel loop isolation (alarm exception doesn't propagate).

## Acceptance
- Replaying the 2026-07-09 sentinel.log through the counters trips both alarms and
  produces exactly two tasks with correct evidence payloads.
- Replaying a healthy day's log produces zero tasks.
