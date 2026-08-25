# P1 queue clearance — Guardrail 8 halt held

- run: 2026-08-25 19:57 UTC (db `now()` 20:00:01 UTC)
- playbook: orch-operator P1-queue-clearance
- outcome: **held**. Steps (a) dead-weight-triage, (b) throughput/concurrency
  raise and (c) prioritize-by-value were not executed.
- task: `log-p1-queue-clearance-guardrail8-held-20260825-r9tz`

Guardrail 8 — no improvement across two consecutive runs, therefore stop and
file an escalate task — has been continuously tripped since 2026-08-10 22:01
UTC and was reaffirmed on 2026-08-14. Every figure below was re-derived by SQL
in this run rather than carried over from a prior one.

## Measured this run

| metric | value | movement |
| --- | ---: | --- |
| `state = QUEUED` | 290 | down from 321 at the 19:00 UTC check |
| `state IN (MERGED, DEPLOYED_AND_VERIFIED)` updated in last 2h | 0 | unchanged |
| p90 queue wait | 1144.0 h (~47.7 d) | up from 1142.9 h at 19:00 UTC |

The QUEUED drop is **not** drain. Zero tasks reached a completed state in the
window, no `bulk_state_change_audit` rows exist for the last 3 h, and
`state = RUNNING` moved 1 → 7 and then wobbled 10/8/7 across three checks. That
is claim churn and individual inserts, not throughput. Meanwhile p90 wait keeps
climbing roughly one hour per hour elapsed, which is what a backlog tail does
when nothing is finishing.

## Root cause — unchanged

- **Global pause**, `scope = global`, set 2026-08-24 04:16:43 UTC (39.7 h, zero
  operator touch). Reason unchanged: hosted providers (google, openai, xai,
  deepseek) out of credit; Claude subscription weekly-limit window until
  2026-08-25 11pm ET (~2026-08-26 03:00 UTC), still ~7 h out at check time.
- **Nine project pauses** (beethoven, darwn, pareto-2080, racefeed,
  santas-secret-workshop, sustainable-barks, kalepasch-com,
  prediction-markets-institute, trojun) set 2026-08-24 03:53–03:57 UTC (~40.1 h)
  for "controlled fleet verification". Their own reason text says the pause is
  reversible and auto-lifts on completion. It has not lifted. This is worse than
  the 39 h reported at the 19:00 check — same unresolved signature.
- **Three host pauses** (claude, Mac.home.local, Mandys-MBP.lan) unchanged since
  2026-08-07 (~448.7 h / 18.7 d). Resuming these requires a human.

## Open human-decision records, all still unactioned

Each was re-confirmed this run by direct id lookup. All are `DECOMPOSED` with
`operator_approved_at` and `operator_approved_by` still NULL.

| slug | age at check |
| --- | ---: |
| `escalate-p1-queue-clearance-no-improvement-20260810-nk73` | 358.0 h / 14.9 d |
| `escalate-p1-queue-clearance-no-improvement-20260814-hlt9` | 266.9 h / 11.1 d |
| `human-decision-unpause-runner-hosts-20260807-tp91` | 432.3 h / 18.0 d |
| `human-decision-stuck-verification-pauses-20260825-k9wq` | 19.0 h |
| `human-decision-p1-halt-bypassed-again3-20260825-k7m2` | 4.0 h |

`k7m2`, filed at 16:01 UTC today, root-caused the repeated halt bypasses to the
`orch-queue-drain-hourly` trigger prompt (`trig_01A9GBrmsQCCHxPpVJPZgWe8`)
lacking a halt-check step. This run followed that guidance and correctly held.

## What was deliberately not done

- No new escalate or human-decision task filed. `k7m2` already covers the
  root-cause finding and remains open; a second one would duplicate it under the
  similar-slug guardrail.
- No push notification. Nothing materially new since the last one (~10 h prior):
  same stuck-pause root cause, same zero-completion signature, the weekly-limit
  boundary not yet reached, and the QUEUED wobble does not reflect real drain.
- Dup-checked first: only one `log-p1-queue-clearance-guardrail8-held-20260825-*`
  row exists in the last 90 minutes (the 19:00:14 entry), so this is the next
  hourly check rather than a repeat.

## Acceptance

A human reviews `nk73`, `hlt9`, `tp91`, `k9wq` and `k7m2`; sets
`operator_approved_at` / `operator_approved_by` or explicitly closes or
supersedes each with a decision; and either authorises resuming the playbook or
formally retires or reschedules it. Separately, confirms why the 2026-08-24
03:53–03:57 UTC controlled-fleet-verification project pauses never auto-lifted,
whether the global pause self-resolves at the stated weekly-limit boundary
(~2026-08-26 03:00 UTC), and whether the `orch-queue-drain-hourly` trigger
prompt should be edited per `k7m2`.

**Done** = none of `nk73`, `hlt9`, `tp91`, `k9wq`, `k7m2` still satisfies
`operator_approved_at IS NULL AND state IN (QUEUED, DECOMPOSED, BLOCKED)`.

## Guardrails observed

No force-push; changes go through `orchestrator/dev`. This entry makes no state
changes to tasks, approvals, releases or runner alerts, and needed no bulk audit
row (single-row insert only). No DELETEs. No host un-pause attempted — that is
human-required. No funding or spend action. No duplicate escalate or
human-decision task created. Swarm-task inserts this run: 1 of a 25 cap.
