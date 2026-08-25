# Guardrail-8 halt held — P1 queue clearance, 2026-08-25

Task: `log-p1-queue-clearance-guardrail8-held-20260825-5h1a` (kind `log`, project `beethoven`).
Every figure below was **re-derived by this run** against the live database rather than
copied from the task prompt. Measurement time: `db now() = 2026-08-25 21:04:29 UTC`.

## Status: halted, and correctly so

Guardrail 8 — *no improvement across two consecutive runs → stop and file an escalation* —
is tripped and stays tripped. This run did **not** execute the three playbook steps it
would otherwise run: dead-weight triage, throughput/concurrency raise, prioritise-by-value.

| measure | value |
|---|---|
| `tasks` in `QUEUED` | 288 |
| `tasks` in `RUNNING` | 3 |
| `MERGED` + `DEPLOYED_AND_VERIFIED` in the last 2 h | **0** |

Zero completions against a 288-deep queue is not a throughput problem to be tuned. It is a
stopped fleet. Raising concurrency against a stopped fleet changes nothing except the token
bill, which is precisely what Guardrail 8 exists to prevent.

## Root cause: `controls` is paused, at three scopes

Confirmed directly from `controls where paused = true` (21 rows):

- **`scope = global`**, paused `2026-08-24 04:16:43 UTC` (**40.8 h**). Reason: every hosted
  provider out of credit (google / openai / xai / deepseek) and the Claude subscription at
  its weekly limit until Aug 25 11pm ET ≈ `2026-08-26 03:00 UTC`. That boundary is still
  **~6 h out** at measurement time, so this pause has not yet had the chance to self-resolve.
- **9 × `scope = project`**, paused `2026-08-24 03:53:42`–`03:57:19 UTC` (**~41.1 h**) for
  "controlled fleet verification", narrowing claimable projects to `smoke-test` alone. Every
  one of these reasons states **REVERSIBLE — lifted when verification finishes**. They have
  not lifted. A pause that advertises its own auto-expiry and then does not expire is a bug,
  not a policy, and it is the single most actionable finding here.
- **3 × `scope = host`** (`claude`, `Mac.home.local`, `Mandys-MBP.lan`), unchanged since
  `2026-08-07 03:18:37 UTC` (**~449.8 h ≈ 18.7 d**), filed under the >7-day dead-host
  threshold. Human-required; no un-pause attempted.

## Five controlling records, all still open

Re-confirmed this run by direct slug lookup. All five have `operator_approved_at IS NULL`
and sit in `DECOMPOSED`:

| slug | age at measurement |
|---|---|
| `human-decision-unpause-runner-hosts-20260807-tp91` | 433.4 h |
| `escalate-p1-queue-clearance-no-improvement-20260810-nk73` | 359.1 h |
| `escalate-p1-queue-clearance-no-improvement-20260814-hlt9` | 268.0 h |
| `human-decision-stuck-verification-pauses-20260825-k9wq` | 20.1 h |
| `human-decision-p1-halt-bypassed-again3-20260825-k7m2` | 5.0 h |

`k7m2` already root-causes the repeated bypasses to the hourly trigger prompt lacking a
halt-check step. No new `escalate` or `human-decision` row was filed this run: `k7m2` covers
the finding and remains open, and filing a near-duplicate slug is itself a guardrail violation.

## Acceptance

Unchanged from prior entries. **Done when** `tp91`, `nk73`, `hlt9`, `k9wq` and `k7m2` no
longer satisfy `operator_approved_at IS NULL AND state IN ('QUEUED','DECOMPOSED','BLOCKED')` —
i.e. a human has approved, closed, or superseded each with an explicit decision — and has
separately answered two questions:

1. Why were the `2026-08-24 03:53–03:57 UTC` controlled-fleet-verification project pauses
   never auto-lifted, given their own reason text promises they would be?
2. Does the `scope = global` pause self-resolve at the stated weekly-limit boundary
   (≈ `2026-08-26 03:00 UTC`), or does it also need a manual lift?

## Guardrails observed by this run

No force-push. No task/approval/release/`runner_alerts` state changed by the log itself.
No `DELETE`. No host un-pause (human-required). No funding or spend action. No duplicate
escalation created — `tp91`/`nk73`/`hlt9`/`k9wq`/`k7m2` were checked first and are all still
open. No push notification sent: nothing has materially changed since the 20:00 UTC check,
so a fresh alert would carry no information prior pushes did not already deliver.
