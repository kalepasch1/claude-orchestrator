# Stranded-branch recovery — batch 1 report (CHECKPOINT, stop here)

2026-08-06. Batch 1 of N is complete. **Stopping for operator review before batch 2**,
as required — a 100+ branch sweep is the exact shape of `M4_bulk_resolved_sweep`,
which manufactured 3,765 phantom merges.

## The measured numbers differ materially from the brief — read this first

The task was written from a measurement taken earlier on 2026-08-06. Re-measured
against `origin` today:

| | task brief | measured now | delta |
|---|---:|---:|---:|
| agent/* branches on origin | 479 | **482** | +3 |
| already merged into master | 250 | **363** | **+113** |
| stranded | 229 | **119** | **−110** |
| of those, merge cleanly | 121 | **103** | −18 |
| would conflict | 108 | **16** | **−92** |

**The backlog is already draining, and fast.** 113 more branches reached master
between the brief being written and this run. That is direct corroboration that
`7ec2d4e` was the correct diagnosis: with the scan window fixed, the merge train
is picking up work it could not see before. Nothing here should be read as the
brief having been wrong — it was right, and the fix it names is working.

The conflict count collapsing from 108 to 16 is the same effect: most of what
"would conflict" was conflicting *with other stranded work*, and resolved itself
as that work landed.

### On the ~1.28M line figure

Do not quote it. Measured with lockfiles, `node_modules`, `vendor`, `dist`,
`.nuxt`, coverage, generated dirs, minified assets and binaries excluded, the
stranded set contains **39,602 real source lines added**. The excluded count came
out at **0**, meaning the current stranded set contains no generated noise at all
— so the 1.28M figure must have been measured over a different population
(most likely including already-merged branches, or via a two-dot rather than
three-dot diff). 39,602 is the honest recoverable figure.

## Root cause: confirmed, and already on master

`7ec2d4e` *"fix(merge): scan-window starvation — the real cause of months of
stranded work"* **is an ancestor of `origin/master`** (verified with
`git merge-base --is-ancestor`). It does address this.

`_pick_cards()` scanned only the newest 3,000 approved cards out of 238,177 rows,
and the train stamps `decided_by` on every card it touches — so that window was
almost entirely already-decided outcomes. A card not merged immediately aged out
within hours and became invisible forever, while `ensure_integration_card` still
found it and refused to file a replacement, so the task could not be re-queued
either. Hence "undecided cards = 0" reported alongside 90 waiting tasks. The fix
scans oldest-first as well, taking `_pick_cards()` from ~0 actionable cards to 103.

**So this task is draining the backlog that fix explains, not re-diagnosing it.**

## What batch 1 recovered: 19 live phantom merges

Cross-referencing the 119 stranded branches against their task rows surfaced the
finding that decided the batch:

| task state | stranded branches |
|---|---:|
| DONE | 42 |
| QUEUED | 22 |
| **MERGED** | **20** |
| QUARANTINED | 13 |
| SUPERSEDED | 9 |
| DECOMPOSED | 8 |
| RUNNING | 4 |
| TESTFAIL | 1 |
| *(no task row)* | 1 |

**20 branches have a task row saying MERGED while the branch is not an ancestor of
master.** That is a live phantom merge — the false-success pattern the 2026-08-04
audit was about, still occurring, with real committed code behind it. It is also
the only category where nothing will ever look at the work again: everything
downstream already believes it is done.

19 of those 20 merge cleanly and were requeued (the 20th does not merge cleanly and
is listed for the operator). Each was an **individual INSERT** carrying its own
provenance note naming its branch, its line delta and the root cause, guarded by
`NOT EXISTS` so a re-run cannot duplicate. New slugs carry the `-recovered` suffix.
All entered as `QUEUED` — **nothing was marked MERGED, nothing was merged directly
to master, and nothing bypassed the merge train, QA or the release train.**

Largest recoveries in the batch:

| branch (task was MERGED) | src lines | files | age |
|---|---:|---:|---:|
| `dropbox-beethoven-fleet-immune-system-...-2-machine-pipeline-heartbeat-alerts-p0` | 1,312 | 7 | 0.9d |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-1` | 1,259 | 6 | 0.2d |
| `dropbox-beethoven-fleet-immune-system-...-1-never-again-lane-daemon-immune-system-p0` | 892 | 5 | 0.9d |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-2` | 676 | 4 | 0.2d |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-3` | 664 | 4 | 0.6d |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-1` | 633 | 4 | 0.2d |
| `improve-pre-decomposition-branch-availability-ve-slice-3-implement-bootstrap-inj` | 601 | 3 | 4.0d |

## What was deliberately NOT requeued

- **42 DONE + 22 QUEUED + 4 RUNNING + 8 DECOMPOSED (76 branches).** These are still
  moving. Post-`7ec2d4e` a DONE task holding a valid card drains on its own;
  requeuing them would duplicate live work and manufacture exactly the churn this
  task warns about.
- **9 SUPERSEDED and 13 QUARANTINED.** Something already decided these were replaced
  or unsafe. Silently reversing that decision would be a guess. They are listed for
  the operator instead — see category (c) below.
- **1 branch with no task row.** Inventoried, not invented. Per the hard rule, no
  task was created for it.

## The 16 conflicting branches

Classified without guessing:

- **(a) superseded** — only where *no source delta remains against master*, i.e.
  there is provably nothing left to recover. That is the sole condition treated as
  definitive.
- **(b) still wanted** — none asserted in this batch. Claiming a branch is still
  wanted requires evidence this pass does not have.
- **(c) unclear → operator** — everything that still carries source changes and
  conflicts. Ambiguity resolves here by design. Closing real work as "superseded"
  on thin evidence destroys it, and that asymmetry is not close.

Per-branch classification is in `ops/stranded-branches-20260806.md`.

## Recommended next step

Do **not** run batches 2..N as a sweep of the remaining 84 clean branches. Most are
DONE/QUEUED and will land on their own now that the train can see them. The correct
next action is to re-measure in 24h: if the merged count keeps climbing, the queue
is self-healing and only the phantom-MERGED and QUARANTINED/SUPERSEDED categories
need human attention.

The one thing worth doing regardless: **the 20 phantom merges found here are new,
not historical.** They were created *after* the 2026-08-04 audit. Whatever writes
`MERGED` without confirming the commit reached master is still doing it. That is a
separate defect from the scan window, and it is the one worth fixing next — it is
the same family as `no-done-without-evidence-cowork-20260806`, which gates DONE but
not MERGED.

## Artifacts

- `ops/stranded-branches-20260806.md` — full 119-branch inventory
- `ops/stranded_branch_inventory.py` — read-only inventory generator
- `ops/stranded_recovery_queue.py` — batched, individually-provenanced requeue
- `ops/tests/test_stranded_recovery.py` — tests for the selection rules
