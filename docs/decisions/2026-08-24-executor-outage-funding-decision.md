# Operator decision: fund provider credits, or wait out the Claude weekly limit

Status: **OPEN — needs the operator.** Automation deliberately does not resolve this;
un-pausing the fleet and authorizing spend are both owner decisions.

## What is true right now

Re-checked against the database at `2026-08-25 02:13 UTC`:

| fact | value |
|---|---|
| `controls` where `scope='global'` | `paused = true` |
| set at / by | `2026-08-24 04:16:43 UTC` by `controlled-verification-2` |
| held for | **~22 hours** |
| paused rows (all scopes) | 20 |
| tasks QUEUED | 438 |
| tasks RUNNING | 1 |
| MERGED / DEPLOYED_AND_VERIFIED in the last 12h | **0** |

The recorded reason: every hosted provider (google / openai / xai / deepseek) is out of
credit, and the Claude subscription is at its weekly limit until **2026-08-25 23:00 ET
(2026-08-26 03:00 UTC)**. A local-only run reached a clean commit but the content was
wrong, and the QA/judge stages route to the same dead providers, so nothing can verify
output either.

## The decision

1. **Fund hosted provider credits** — restores QA/judge routing immediately, costs money.
2. **Wait for the Claude weekly reset** — free, but ~25 more hours of a dead fleet on top
   of the 22 already lost, and the queue keeps growing.

## Acceptance

A human sets `paused = false` on the `scope='global'` controls row, **and** a follow-up
check of `MERGED`/`DEPLOYED_AND_VERIFIED` within the last 2 hours returns > 0 — i.e. real
throughput actually resumed, not just the flag flipped.

## What was fixed alongside this

The outage ran 22 hours without an alarm. `fleet_stuck_alarm.py` only tripped on
`queued > 0 AND running == 0`, and `running` was 1 — a single straggler that never
released its lane — so the alarm reported "healthy" through a total freeze. It now also
trips when the global pause has been held past `ORCH_PAUSE_MAX_AGE_S` (default 4h), and
the approval card names the pause as the cause. See
`runner/tests/test_fleet_stuck_alarm_pause_age.py`.

## Not done, on purpose

- The global pause was **not** lifted. That is the operator's call.
- The 9 project-scope pauses set ~03:53–03:57 UTC on 2026-08-24 for a separate
  "controlled fleet verification" (marked REVERSIBLE / self-lifting) were left alone —
  different process, possibly still in progress.
- No rows deleted; no spend authorized.
