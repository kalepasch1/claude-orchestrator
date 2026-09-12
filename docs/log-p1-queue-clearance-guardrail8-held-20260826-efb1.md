# P1-queue-clearance — Guardrail 8 held (run 2026-08-26 ~19:02 UTC)

**Kind:** `log` · **Slug:** `log-p1-queue-clearance-guardrail8-held-20260826-efb1`
**State changes made:** none. No writes to `tasks`, `approvals`, `releases`, or
`runner_alerts`. No `bulk_state_change_audit` row required.

## What was held

Guardrail 8 (*no improvement across two consecutive runs → stop and escalate
rather than continue*) has been tripped continuously since **2026-08-10 22:01
UTC** and remains unresolved by a human. Three steps of the orch-operator
P1-queue-clearance playbook were therefore **not** executed this run:

| step | status |
|---|---|
| (a) dead-weight triage | held |
| (b) throughput / concurrency raise | held |
| (c) prioritize-by-value | held |

## Metrics, re-derived this run

Every figure below was queried directly this session rather than carried over
from a prior run's log. `db now() = 2026-08-26 19:02:42 UTC`.

| metric | this run (19:02) | 18:59 | 18:00 | 13:02 |
|---|---|---|---|---|
| `tasks` QUEUED | 174 | 174 | 206 | 264 |
| `tasks` RUNNING | 3 | 4 | 4 | 1 |
| p90 queued-task wait | 1167.2 h (~48.6 d) | 1167.1 h | 1166.1 h | 1161.1 h |

The raw QUEUED count has fallen over the day (264 → 174), but **that is not
throughput**: the p90 queued wait has risen monotonically across the same
window (1161.1 → 1167.2 h). Work is leaving the queue by attrition and
triage, not by being executed, while the oldest 10 % of the backlog keeps
ageing at wall-clock rate. That is precisely the "no improvement across two
consecutive runs" condition Guardrail 8 exists to catch, and it has now held
for **16 days**.

RUNNING = 3 is again effectively zero real utilisation — one of those rows is
this executor's own claim on this very task.

## Root blocker (unchanged, now further past its own ETA)

```
controls WHERE scope='global' → paused = true
                                updated_at = 2026-08-24 04:16:43 UTC
                                stale for  = 62.8 h
```

The pause reason cites a 2026-08-24 executor outage (google / openai / xai /
deepseek all out of credit) plus a Claude weekly-limit reset ETA of
**Aug 25 11pm ET ≈ 2026-08-26 03:00–04:00 UTC**. That ETA is now roughly
**15 h in the past**, the control row has still not been updated or lifted,
and no throughput recovery has followed. Lifting a global pause is
human-required; no un-pause was attempted.

## Escalation dedup — all seven targets still open

Checked by direct slug lookup this run. Every one is `DECOMPOSED` with
`operator_approved_at IS NULL`. No new escalation task was filed, because
these already cover this exact condition and the guardrail on duplicate
swarm-task inserts forbids piling on.

| slug | age |
|---|---|
| `escalate-p1-queue-clearance-no-improvement-20260810-nk73` | 15.9 d |
| `escalate-p1-queue-clearance-no-improvement-20260814-hlt9` | 12.1 d |
| `human-decision-maclan-dirty-tree-lockup-20260817-dr71` | 9.4 d |
| `human-decision-p1-halt-bypassed-again2-20260821-qz84` | 5.7 d |
| `human-decision-stuck-verification-pauses-20260825-k9wq` | 1.8 d |
| `human-decision-p1-halt-bypassed-again3-20260825-k7m2` | 1.1 d |
| `human-decision-global-pause-past-eta-20260826-fq83` | 0.6 d |

## Bypass check — clean this cycle

`bulk_state_change_audit` has **0 rows since 2026-08-26 00:00 UTC**. The halt
held cleanly today with no rogue execution to flag, in contrast to the six
documented bypass incidents between 2026-08-11 and 2026-08-25.

## What re-opens the playbook

Guardrail 8 lifts only when a human sets `operator_approved_at` on one of the
open `human-decision-*` / `escalate-p1-queue-clearance-*` tasks above, **or**
the `controls` global pause is lifted with a fresh `updated_at`. Until then
every scheduled run of this playbook should hold and log, exactly as this one
did.

## Guardrails observed

- Did not execute steps (a) / (b) / (c).
- Did not raise concurrency.
- Did not file a duplicate escalation task.
- Did not lift or edit the global pause.
- No rows deleted, no force-push, no push to `master`.
