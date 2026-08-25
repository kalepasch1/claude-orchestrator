# P1 queue clearance — Guardrail 8 held again (2026-08-25 ~06:00 UTC)

**Slug:** `log-p1-queue-clearance-guardrail8-held-20260825-qw52`
**Kind:** log (operator record — no code or data change required to close)
**Outcome:** run held Guardrail 8. Steps (a) dead-weight triage, (b) throughput/concurrency
raise, and (c) prioritize-by-value were **not** executed.

## Why the run held

Guardrail 8 blocks the P1 clearance steps while the queue shows no improvement. That
condition is still tripped, and the p90 wait is still climbing.

## Measurements

The orch-operator's numbers were re-queried independently by the executor at
`db now() = 2026-08-25 06:15:24 UTC`, ~15 minutes after the operator run. Both columns
are shown so the drift is visible rather than smoothed over.

| Metric | Operator run (~06:00 UTC) | Executor re-check (06:15 UTC) |
| --- | --- | --- |
| `tasks` QUEUED | 359 | 358 |
| `tasks` RUNNING | 7-11 (fluctuating) | 10 |
| MERGED / DEPLOYED_AND_VERIFIED, last 2h | 0 | 0 |
| MERGED / DEPLOYED_AND_VERIFIED, last 24h | 1 | 1 |
| p90 queued-task wait | 1129.8 h (~47.1 d) | 1130.1 h (~47.1 d) |

p90 wait is `percentile_cont(0.9)` over queued-task age in hours.

Reading of the numbers:

- **Queue depth is noise, not a trend.** 398 -> 363 -> 359 -> 358 across the 04:00,
  ~05:55, 06:00 and 06:15 checks is churn inside the normal band, not drainage.
- **p90 wait is the signal.** It rose again between the operator run and the re-check
  (1129.8 -> 1130.1 h). That is the twelfth-plus consecutive measurement showing a
  monotonic increase, now 11+ days unbroken. Guardrail 8's no-improvement condition
  is satisfied on this metric alone.
- **Throughput is effectively dead.** 0 integrations in 2 h and 1 in 24 h, against 358
  claimable tasks. The 24 h figure is *worse* than the 2/24h reported at 04:00 UTC.
- **Concurrency is the bottleneck's symptom, not its cause.** 10 RUNNING against
  hundreds of claimable slots is what the step (b) raise would target — but raising
  concurrency while the fleet is paused would add no throughput.

## Fleet state re-verified as unchanged since 04:00 UTC

- `controls` scope=global `paused=true` since **2026-08-24 04:16:43 UTC** (~26 h,
  zero operator touch). Stated reason: executor outage / hosted providers out of
  credit; Claude weekly limit until Aug 25 11pm ET, not yet reached at check time.
- 16 host- and project-scope `controls` rows also still `paused=true`.
- `runner_alerts`: 1 open `host_update` ESCALATED alert (id 10716, 22 consecutive
  cycles, diagnosis `git-error "Cannot fast-forward to multiple branches"` on
  `Mac.lan`). Same class as the already-tracked
  `human-decision-mac-lan-fast-forward-diverged-20260808-fw31` — not new.
- `scheduler_snapshot_stale` alerts continuing (~34 days stale). Already known.

## Duplicate check — no new task filed this run

All findings map to existing open tasks. Approval state re-verified by the executor:

| Slug | State | `operator_approved_at` / `_by` |
| --- | --- | --- |
| `escalate-p1-queue-clearance-no-improvement-20260814-hlt9` | DECOMPOSED | NULL / NULL — open 11 days |
| `human-decision-load-runner-launchd-20260825-lc91` | DECOMPOSED | NULL / NULL |
| `human-decision-stuck-verification-pauses-20260825-k9wq` | DECOMPOSED | NULL / NULL |
| `human-decision-mac-lan-fast-forward-diverged-20260808-fw31` | DECOMPOSED | NULL / NULL |

`human-decision-fund-executor-outage-20260824-qz4m` is state=DONE with
`operator_approved_at` NULL. That was flagged at 04:00 UTC as a possible process gap —
a human-decision task reaching DONE without an approval stamp — and is deliberately
**not** re-flagged here to avoid duplicate noise. It remains worth a look.

No `escalate-*` or `human-decision-*` task was created this run.

## Notification

No PushNotification sent. Nothing is new or materially changed versus the 04:00 UTC
run, which already surfaced the one new actionable item (the launchd fix) to the
operator. Re-notifying on an unchanged, already-flagged standing condition is noise
under the notification guidance.

## Acceptance

No code or data change is required to close this log entry.

P1 steps (a), (b) and (c) may resume once a human sets `operator_approved_at` and
`operator_approved_by` on `escalate-p1-queue-clearance-no-improvement-20260814-hlt9`
with an explicit **resume** or **retire** decision. Until then every P1 clearance run
will hold and produce another entry like this one.

## Guardrails observed

No force-push; changes go through `orchestrator/dev`; no bulk state changes (so no
audit row needed); no DELETEs; no host un-pause or launchd action attempted
(host-only, human-required); no funding or spend action taken; no duplicate
escalate/human-decision task created (existing slugs checked first); swarm-task
inserts this run 1 of 25 cap.
