# P1 Queue Clearance — Guardrail 8 Halt Log

**Status: HELD. The playbook is not running and must not be resumed by an agent.**

Guardrail 8 ("no improvement across two consecutive runs → stop, file an escalate
task") has been continuously tripped since **2026-08-10 22:01 UTC**. Every hourly
`orch-operator` P1-queue-clearance session since then has re-measured the queue,
confirmed the halt still holds, logged, and stopped without executing the
playbook's action steps.

This file is the in-repo record of that state, because the five records that
control it are all sitting in the database unactioned and are therefore invisible
to anyone reading the repo.

## Why this is held

The halt is not caused by the queue-clearance logic. It is caused by paused
runner controls that no agent may lift:

| scope | what | paused since | age at 2026-08-25 22:59 UTC |
|---|---|---|---|
| global | hosted providers out of credit; Claude weekly-limit window to ~2026-08-26 03:00 UTC | 2026-08-24 04:16:43 UTC | 42.7h |
| project ×9 | "controlled fleet verification" — reason text claims REVERSIBLE / auto-lift on completion; **it never lifted** | 2026-08-24 03:53–03:57 UTC | ~43.0h |
| host ×3 | `claude`, `Mac.home.local`, `Mandys-MBP.lan` — human-required unpause | 2026-08-07 | ~451.7h / 18.8d |

The nine project-scope pauses are the anomaly worth a human's attention: they
were written as self-lifting and did not self-lift.

## Measured state (independently re-derived 2026-08-25 22:59 UTC)

- queued: **284**
- running: **2**
- completed (`MERGED` / `DEPLOYED_AND_VERIFIED`) in the last 2h: **0**
- p90 queued-task wait: **1147.0h (~47.8d)**, up from 1144.0h at the 21:00 UTC
  check — the backlog tail is aging in lockstep with wall-clock time, which is
  the signature of zero drain rather than slow drain.

## Open records blocking resumption

All five re-confirmed open and unactioned (`operator_approved_at IS NULL`):

| slug | kind | age | covers |
|---|---|---|---|
| `escalate-p1-queue-clearance-no-improvement-20260810-nk73` | DECOMPOSED | 361.0h / 15.0d | original guardrail-8 escalation |
| `escalate-p1-queue-clearance-no-improvement-20260814-hlt9` | DECOMPOSED | 269.9h / 11.2d | reaffirmation |
| `human-decision-unpause-runner-hosts-20260807-tp91` | — | 435.3h | the three host-scope pauses |
| `human-decision-stuck-verification-pauses-20260825-k9wq` | — | 22.0h | the nine non-lifting project pauses |
| `human-decision-p1-halt-bypassed-again3-20260825-k7m2` | — | 7.0h | root cause: the hourly trigger prompt has no halt-check step |

`k7m2` is the one with a fix attached to it. Earlier bypasses of this halt
happened because the hourly trigger prompt does not check the halt before
running the playbook — the guard exists in the playbook's own conventions but
not in the thing that invokes it.

## Acceptance — all of it is human work

Done when `nk73`, `hlt9`, `tp91`, `k9wq`, and `k7m2` no longer satisfy
`operator_approved_at IS NULL AND state IN ('QUEUED','DECOMPOSED','BLOCKED')`.

That means a human, for each record, either sets
`operator_approved_at` / `operator_approved_by` or explicitly closes/supersedes
it with a decision, and then either authorizes resuming the playbook or formally
retires / re-schedules it. Separately: confirm why the 2026-08-24 03:53–03:57 UTC
controlled-fleet-verification project pauses never auto-lifted, and whether the
global pause self-resolves at the stated weekly-limit boundary
(~2026-08-26 03:00 UTC).

## What agents must not do here

- Do not un-pause hosts — human-required.
- Do not take a funding or spend action to clear the provider credit exhaustion.
- Do not file another escalate / human-decision task — `nk73`, `hlt9`, and
  `k7m2` already cover the escalation and the root cause; a sixth record is a
  duplicate under the dedup guardrail.
- Do not resume the playbook's action steps (dead-weight triage, throughput /
  concurrency raise, prioritize-by-value) while the halt holds.

Each hourly check should dup-check the most recent
`log-p1-queue-clearance-guardrail8-held-*` row before logging, and should skip
the push notification when nothing has materially changed since the previous
check.
