# P1-queue-clearance — Guardrail 8 held, run 2026-08-26

Kind: `log`. No state changes to `tasks`, `approvals`, `releases`, or
`runner_alerts` were made by this run. Acceptance is human review, not code.

## Status carried forward

Guardrail 8 (no improvement across two consecutive runs → stop, file escalate)
is still tripped, continuously since 2026-08-10. Both escalation tasks remain
open with `operator_approved_at IS NULL`:

| slug | filed | state | age |
|---|---|---|---|
| `escalate-p1-queue-clearance-no-improvement-20260810-nk73` | 2026-08-10 22:01 UTC | DECOMPOSED | ~15d |
| `escalate-p1-queue-clearance-no-improvement-20260814-hlt9` | 2026-08-14 17:03 UTC | DECOMPOSED | ~11d |
| `human-decision-stuck-verification-pauses-20260825-k9wq` | 2026-08-25 | open | ~1d |

Steps (b) throughput/concurrency raise and (c) prioritize-by-value were not
executed: `MAX_PARALLEL`/`ORCH_MAX_PARALLEL`/`MAX_PARALLEL_CEILING` are 20/16/24
against 2–3 tasks actually RUNNING, so concurrency is not the binding
constraint, and the live QUEUED priority range is 1–70 (median 35), which means
step (c)'s literal `priority=5` would rank a task *below* ~240 of the 278
already-queued tasks. That scale mismatch needs an operator decision before the
step is ever run for real.

## New this run: the queue is not slow, it is deadlocked

Prior runs recorded the symptom (278 QUEUED, 0 merges in 4h, p90 wait ~1149h).
This run measured *why* nothing is claimable, which had not been recorded before.

Re-running the executor claim predicate against the live table:

```
queued_total        278
queued_with_project 277
eligible_now          0
```

Zero. Not "few" — every remaining QUEUED task fails the dependency gate. Broken
down by the state of the blocking dep:

| blocking dep state | blocked tasks | can it ever clear? |
|---|---|---|
| DECOMPOSED | 88 | no — a decomposed parent never itself reaches DONE/MERGED |
| QUEUED | 61 | only if that dep becomes claimable, which it also is not |
| SUPERSEDED | 53 | **no** — terminal |
| QUARANTINED | 35 | **no** — terminal |
| CLOSED | 28 | **no** — terminal |
| NO_SUCH_TASK | 8 | **no** — dep slug matches no row in the project |
| PHANTOM_UNVERIFIED | 4 | **no** — terminal |

128 tasks are blocked on deps that are terminally resolved but not `DONE`/
`MERGED`, plus 88 on `DECOMPOSED` parents: **216 of 277 are deadlocked by
construction**, not waiting on work. The remaining 61 wait on QUEUED deps that
are themselves inside the same deadlock, so the true figure is the whole queue.

By project:

| project | terminal-dep blocked | DECOMPOSED-dep blocked | QUEUED-dep blocked | total |
|---|---|---|---|---|
| beethoven | 94 | 46 | 30 | 170 |
| tomorrow | 10 | 17 | 11 | 38 |
| sustainable-barks | 5 | 12 | 6 | 23 |
| santas-secret-workshop | 6 | 1 | 7 | 14 |
| darwn | 5 | 2 | 5 | 12 |
| kalepasch-com | 4 | 7 | 0 | 11 |
| pareto-2080 | 4 | 2 | 2 | 8 |
| racefeed | 0 | 1 | 0 | 1 |

## Where the predicate lives

`runner/migrations/001_claim_next_rpc.sql`. Its 2026-08-25 comment block already
corrects two adjacent bugs (cross-project `project:slug` deps, and
`DEPLOYED_AND_VERIFIED` being treated as a blocker) and states plainly that
neither correction unblocks the deadlock. The measurement above says what does:
the gate's *satisfied* set is `('DONE','MERGED','DEPLOYED_AND_VERIFIED')`, while
the set of states a dep can terminally come to rest in is strictly larger.
`SUPERSEDED`, `CLOSED` and `QUARANTINED` all mean "this will not be done, and
nothing is waiting on it any more" — but the gate reads them as "not finished
yet" and holds every dependent forever.

The same predicate is duplicated verbatim in all 16 `cowork-skills/
cowork-executor*.SKILL.md` files, so a fix to the RPC alone leaves the Cowork
executors deadlocked.

## What a human has to decide

Not implemented here — this is a `log` task, and changing the fleet-wide claim
gate under a log slug is exactly the unscoped change the guardrails exist to
prevent. The decisions needed:

1. Should `SUPERSEDED` / `CLOSED` / `QUARANTINED` count as dependency-satisfying?
   Arguments both ways: a dependent of superseded work may have been made
   pointless by the supersession, or may be entirely independent of *why* it was
   superseded. A blanket "terminal counts as satisfied" clears 128 tasks but may
   run work that should have died with its parent.
2. Should a `DECOMPOSED` parent be satisfied by *all its children* reaching
   DONE/MERGED? That is the semantically correct rule and clears 88 more.
3. The 8 `NO_SUCH_TASK` deps are data errors and can be cleared by editing those
   8 task rows regardless of 1 and 2.
4. Whether the 2026-08-24 03:53–03:57 UTC controlled-fleet-verification project
   pauses (9 projects) were meant to auto-lift, and whether the global pause
   self-resolved at the ~2026-08-26 03:00 UTC weekly-limit boundary.
5. The correct target value for playbook step (c) given the live 1–70 priority
   scale.

Done = `nk73`, `hlt9`, `tp91`, `k9wq`, `k7m2` no longer have
`operator_approved_at IS NULL AND state IN ('QUEUED','DECOMPOSED','BLOCKED')`.
