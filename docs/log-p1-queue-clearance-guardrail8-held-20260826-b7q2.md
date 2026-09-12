# P1-queue-clearance — Guardrail 8 held, run 2026-08-26 10:59 UTC

Kind: `log`. This run made **zero** state changes to `tasks`, `approvals`,
`releases`, or `runner_alerts`. No `bulk_state_change_audit` row was required
(single-row log insert only). Acceptance is human review, not code.

Steps held this run: (a) dead-weight triage, (b) throughput/concurrency raise,
(c) prioritize-by-value.

## Guardrail 8 status: still tripped

Guardrail 8 — *no improvement across two consecutive runs → stop, file an
escalate task instead of continuing* — has been continuously tripped since
2026-08-10 22:01 UTC. Both escalations remain open and unactioned, so no third
duplicate was filed (check-existing-similar-slug-first rule).

| slug | filed (UTC) | state | `operator_approved_at` | age at run |
|---|---|---|---|---|
| `escalate-p1-queue-clearance-no-improvement-20260810-nk73` | 2026-08-10 22:01 | DECOMPOSED | NULL | 15.5d |
| `escalate-p1-queue-clearance-no-improvement-20260814-hlt9` | 2026-08-14 17:03 | DECOMPOSED | NULL | 12.2d |

## Measurements taken this run (all re-derived, no carried-forward numbers)

Database clock at time of the run: `2026-08-26 10:59 UTC`.

| metric | value | direction |
|---|---|---|
| `count(*) tasks WHERE state='QUEUED'` | 267 | flat |
| `count(*) tasks WHERE state='RUNNING'` | 0 | stalled |
| p90 queued-task wait (`percentile_cont(0.9)` over age hours) | 1159.0h (~48.3d) | **worsening** |

The p90 wait is on a continuous multi-day climb and did not improve at any
point in the observation window:

| time (UTC) | p90 wait |
|---|---|
| 2026-08-26 07:00 | 1155.0h |
| 2026-08-26 08:00 | 1156.0h |
| 2026-08-26 10:02 | 1158.0h |
| 2026-08-26 10:59 | **1159.0h** |

Flat-to-worse on every reading. That is precisely the Guardrail 8 condition, so
the playbook halted rather than continuing to churn.

## Root blocker: the global pause is now past its own stated ETA

```sql
SELECT scope, paused, reason, updated_at FROM controls WHERE paused = true;
```

The binding row is `scope=global, paused=true`, last touched
**2026-08-24 04:16:43 UTC** — 54.7 hours stale at the time of this run. Its
`reason` cites two things:

1. an executor outage (google / openai / xai / deepseek all out of credit), and
2. a Claude weekly-limit reset ETA of **Aug 25, 11pm ET** (≈ 2026-08-26
   03:00–04:00 UTC).

`date -u` at run time was `2026-08-26 10:59 UTC`. **That ETA is roughly seven
hours in the past, and the `controls` row has not been updated since 08-24.**
Either the reset did not resolve the outage, or no operator has revisited the
pause since it was set. The queue cannot drain while it stands.

This exact finding was already filed as
`human-decision-global-pause-past-eta-20260826-fq83` (2026-08-26 04:01 UTC,
state `DECOMPOSED`, still unactioned). Confirmed open by direct slug lookup this
run and deliberately **not** re-filed as a duplicate.

## Why the held steps were held

- **(a) dead-weight triage** — a triage pass mutates task state. With the global
  scope paused and Guardrail 8 tripped, no state changes are in scope.
- **(b) throughput/concurrency raise** — `RUNNING = 0`. Concurrency is not the
  binding constraint; raising a parallelism ceiling against zero running work
  changes nothing. The constraint is upstream, at the paused global control.
- **(c) prioritize-by-value** — reordering a queue that nothing can claim moves
  no work. It would also burn a bulk state change against a queue whose real
  blocker is a funding/credentials decision.

## Guardrails observed

- Never force-push. Change routes through `orchestrator/dev`.
- **No un-pause attempted.** Un-pausing a paused scope is a human/funding
  decision per this playbook's own guardrails — this automation flags it via
  notification rather than acting on it.
- No `DELETE`s, no bulk priority update, no funding or spend action.
- No duplicate escalate/human-decision task filed for an already-open topic;
  dedup confirmed against `nk73`, `hlt9`, and `fq83` before deciding.

## Acceptance

A human reviews `nk73`, `hlt9`, and `fq83`; sets `operator_approved_at` /
`operator_approved_by` or explicitly closes/supersedes each with a decision; and
then either authorizes resuming the P1-queue-clearance playbook or formally
retires / re-schedules it.

## Independent re-verification at commit time (2026-08-26 11:57 UTC)

The executor writing this file re-ran the same queries an hour after the
playbook run, so the record carries a second, independent reading rather than
only the playbook's own numbers.

| metric | 10:59 UTC (run) | 11:57 UTC (commit) | verdict |
|---|---|---|---|
| QUEUED | 267 | 265 | noise-level drift, not drain |
| RUNNING | 0 | 3 | executor activity resumed; still no merges |
| p90 wait | 1159.0h | **1160.0h** | still climbing |
| MERGED/DEPLOYED_AND_VERIFIED in last 4h | 0 | **0** | throughput still zero |
| open `human-decision-%` tasks | 25 | 25 | unchanged |

`RUNNING` moving 0 → 3 is this executor's own claim, not fleet recovery: the
4-hour merge count is still **0**. Work is being picked up and not landing.

The `scope=global` pause row is unchanged at `updated_at = 2026-08-24
04:16:43 UTC`, now **55.7 hours stale** and ~8 hours past its stated ETA. All
four referenced decision tasks are still `DECOMPOSED` with
`operator_approved_at IS NULL`:

| slug | created (UTC) | state |
|---|---|---|
| `escalate-p1-queue-clearance-no-improvement-20260810-nk73` | 2026-08-10 22:01 | DECOMPOSED |
| `escalate-p1-queue-clearance-no-improvement-20260814-hlt9` | 2026-08-14 17:03 | DECOMPOSED |
| `human-decision-stuck-verification-pauses-20260825-k9wq` | 2026-08-25 01:00 | DECOMPOSED |
| `human-decision-global-pause-past-eta-20260826-fq83` | 2026-08-26 04:01 | DECOMPOSED |

Conclusion unchanged: the Guardrail 8 hold is correct and the blocker is a
pending human decision, not a scheduling or capacity problem.
