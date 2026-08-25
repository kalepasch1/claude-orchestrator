# P1-queue-clearance held under Guardrail 8 — 2026-08-25

**Check time:** 2026-08-25 20:34:35 UTC (database `now()`)
**Task:** `log-p1-queue-clearance-guardrail8-held-20260825-3haw`
**Outcome:** held. No drain steps executed, no fleet state changed.

Guardrail 8 says: if two consecutive runs of the P1-queue-clearance playbook show
no improvement, stop and escalate rather than keep pulling the same lever. That
condition has been true continuously since 2026-08-10 and is true again here, so
this run did **not** execute dead-weight triage, did **not** raise throughput or
concurrency, and did **not** re-prioritise by value.

Every number below was re-derived from the database during this run. Nothing is
carried forward from an earlier check.

## What the queue looks like

| Measure | Value |
|---|---|
| Tasks `QUEUED` | 288 |
| Tasks `RUNNING` | 4 |
| Reached `MERGED` / `DEPLOYED_AND_VERIFIED` in the last 2 h | **0** |
| p90 wait for a queued task | **1144.6 h** (47.7 days) |

Two of those rows are the whole story.

Nothing has completed in two hours. Not slowly — zero. The `QUEUED` count moving
around in the 288–321 band across recent checks is executors claiming tasks and
releasing them again, not work leaving the queue. Claim churn looks like drain
if you only watch the count.

The p90 wait is the honest measure, and it climbs roughly an hour for every hour
of wall clock. That is the signature of a queue whose tail is not being served at
all: the oldest 10% simply age. A queue that was draining slowly would show the
p90 flattening or sawtoothing. This one tracks the clock.

## Why nothing is moving

The fleet is paused, and has been for the better part of two days.

**Global pause — 40.3 h, untouched.** Set 2026-08-24 04:16:43 UTC by
`controlled-verification-2`. Its stated reason: every hosted provider is out of
credit (google, openai, xai, deepseek) and the Claude subscription is at its
weekly limit until Aug 25 11 pm ET. The compounding part is that the QA and judge
stages route to those same dead providers, so even a local-only run that reaches a
clean commit has nothing available to verify its output.

That weekly-limit boundary is 2026-08-26 03:00 UTC — about 6.4 hours after this
check. It has not been reached yet, so this run cannot report whether the global
pause self-resolves there. The next check after that boundary can.

**Nine project pauses that promised to lift themselves — 40.6 h, not lifted.**
Set 2026-08-24 03:53–03:57 UTC by `controlled-verification` across `beethoven`,
`darwn`, `pareto-2080`, `racefeed`, `santas-secret-workshop`, `sustainable-barks`,
`kalepasch-com`, `prediction-markets-institute`, and `trojun`. Each reason string
says, in its own words, `REVERSIBLE — lifted when verification finishes`.

The verification is over. The pauses are not lifted. Whatever was meant to lift
them either never ran or never existed, and the text of the pause is now actively
misleading anyone who reads it: it describes a self-clearing state that does not
self-clear. A pause that claims it will lift itself and then does not is worse
than one that says a human must lift it, because nobody goes looking for it.

**Three host pauses — 449.3 h (18.7 days).** `claude`, `Mac.home.local`, and
`Mandys-MBP.lan`, all set 2026-08-07 by `orch-operator-bootstrap` under the
>7-day dead-host rule. These are correctly human-gated; the automation should not
lift them and does not try. Noted so the total is legible, not as a complaint.

There are 16 paused projects in all. The seven not listed above (`vigil`,
`apparently`, `apparently-law`, `tomorrow`, `illuminati`, `smarter`, `my-app`) are
older and separately reasoned. One deserves a line: `my-app` has been paused since
2026-08-19 with `updated_by = 'test'` and the reason `test`. That is a leftover
test fixture sitting in a production control table, and it should be deleted.

## The four records this is actually waiting on

All four are `state = DECOMPOSED` with `operator_approved_at IS NULL`. None has
been touched.

| Slug | Age |
|---|---|
| `human-decision-unpause-runner-hosts-20260807-tp91` | 432.9 h (18.0 d) |
| `escalate-p1-queue-clearance-no-improvement-20260810-nk73` | 358.6 h (14.9 d) |
| `escalate-p1-queue-clearance-no-improvement-20260814-hlt9` | 267.5 h (11.1 d) |
| `human-decision-stuck-verification-pauses-20260825-k9wq` | 19.6 h |

Guardrail 8 fired correctly and produced escalations. The escalations went
nowhere. This is the loop the playbook is stuck in: it detects that it cannot
help, files a record saying so, and that record joins three older ones saying the
same thing. Filing a fifth would not add information, so this run did not file
one.

## What would end this

A human reviews `tp91`, `nk73`, `hlt9`, and `k9wq`, and for each one either sets
`operator_approved_at` / `operator_approved_by` or explicitly closes or supersedes
it with a decision — then either authorises resuming the playbook or formally
retires it.

Separately, two questions need answers that only a human has:

1. Why were the 2026-08-24 03:53–03:57 UTC controlled-fleet-verification project
   pauses never lifted, given they declare themselves reversible and
   self-clearing? Either the lifting mechanism is broken and should be fixed, or
   it never existed and the reason text should stop claiming it does.
2. Does the global pause clear on its own at the 2026-08-26 03:00 UTC weekly-limit
   boundary, or does it need the funding decision it references?

**Done means:** none of `tp91`, `nk73`, `hlt9`, `k9wq` still matches
`operator_approved_at IS NULL AND state IN ('QUEUED','DECOMPOSED','BLOCKED')`.

## Notification

No push sent this run. The last confirmed push went with the 10:01 UTC check,
about 10.5 hours earlier, and nothing since then is materially new — same stuck
pauses, same zero throughput, same four unactioned records, and the weekly-limit
boundary still ahead rather than behind. The established cadence is roughly every
16–24 hours, or immediately on a genuinely new development. The next such
development is the 03:00 UTC boundary passing, which the following check will be
able to report on either way.

## Guardrails observed

No force-push. No writes to `tasks`, `approvals`, `releases`, or `runner_alerts`.
No deletes. No pause lifted or created, including the host pauses, which are
human-only by design. No funding or spend action. No duplicate escalate or
human-decision record — `tp91`, `nk73`, `hlt9`, and `k9wq` were each looked up by
slug first and confirmed still open. This record changes no fleet state; its whole
deliverable is the record itself.
