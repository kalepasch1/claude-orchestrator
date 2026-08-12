# Stranded-branch recovery — batch 2 (re-measure + the writer that was still leaking)

2026-08-12. Batch 1 (`ops/stranded-recovery-batch-1-report.md`) ended with two
instructions. This slice executes both:

> Do **not** run batches 2..N as a sweep of the remaining 84 clean branches. […]
> The correct next action is to re-measure in 24h.

> The one thing worth doing regardless: **the 20 phantom merges found here are new,
> not historical.** […] Whatever writes `MERGED` without confirming the commit
> reached master is still doing it.

No sweep was run. The re-measure is below; the writer was found and fixed.

## Re-measure — the rate improved, the backlog did not

Measured against `origin/master`, same read-only tool, same exclusions:

| | 2026-08-06 (batch 1) | 2026-08-12 (now) | delta |
|---|---:|---:|---|
| `agent/*` branches on origin | 482 | **962** | +480 (×2.0) |
| already merged into master | 363 | **768** | +405 |
| **stranded** | 119 | **194** | **+75** |
| of those, merge cleanly | 103 | **124** | +21 |
| would conflict | 16 | **70** | **+54** |
| merged share | 75.3% | **79.8%** | +4.5 pts |

**Read this carefully, because the two obvious readings are both wrong.**

*Not* "the fix regressed": the merged **share** rose from 75.3% to 79.8%, and 405
branches reached master in six days versus 113 in the days before. The train is
draining faster than it ever has. `7ec2d4e` is holding.

*Not* "the fix worked, we're done" either: branch **creation** doubled in the same
window, so an improving rate still leaves a growing absolute backlog — 194 stranded
today against 119 six days ago. Batch 1's projection ("most are DONE/QUEUED and will
land on their own") was right about the branches it measured and wrong about the
total, because it did not model new arrivals.

The conflicting set is where this bites: 16 → 70. Batch 1 correctly explained the
earlier collapse (108 → 16) as stranded work un-conflicting itself as it landed. The
reverse is now happening — 480 new branches forked from a base that is moving fast,
and they conflict with each other.

### Source-line figures

276,374 real source lines added across the stranded set; **0 lines excluded** as
lockfile / build output / vendored / binary, same as batch 1. The ~1.28M figure in
the original brief still must not be quoted.

Median is **250** source lines per branch, so the total is not a few giants. The
largest are:

| branch | src lines | files | age (d) |
|---|---:|---:|---:|
| `chatgpt-local-reconcile-beethoven-286879fa5fe4` | 44,697 | 6 | 0.1 |
| `chatgpt-local-reconcile-beethoven-44d6bb63e4fc` | 44,697 | 6 | 0.1 |
| `chatgpt-local-reconcile-beethoven-d64eac25eb52` | 22,591 | 4 | 0.2 |
| `chatgpt-local-reconcile-beethoven-6e398b6bdfef` | 11,548 | 3 | 0.2 |
| `improve-compliance-scheduling-observability` | 7,603 | 99 | 0.2 |
| `copyfix-beethoven-07180848-slice-3-public-landing-domain-intent-labels` | 7,450 | 51 | 5.8 |

The top two are byte-identical in size and hours old — `chatgpt-local-reconcile-*`
accounts for 123,533 of the 276,374 lines (45%) across 8 branches. That population
deserves its own look before anyone treats 276k as recoverable human work; it is
flagged here rather than assumed either way.

By slug prefix: `dropbox-*` 77, `canary-*` 39, `improve-*` 29, `chatgpt-*` 8,
`copyfix-*` 6, `backlog-*` 5, `relfix-*` 5, `recover-*` 4.

## Conflict classification — all 70 land in (c)

Applying the same rule as batch 1, where the *only* condition treated as definitive
for "superseded" is that no source delta remains against master:

- **(a) superseded — 0.** Not one of the 70 has a zero delta. There is nothing here
  that is provably safe to close.
- **(b) still wanted — 0 asserted.** Same reason as batch 1: claiming it requires
  evidence this pass does not have.
- **(c) unclear → operator — 70.** Per-branch detail in
  `ops/stranded-branches-20260812.md`.

Ambiguity resolving to (c) is deliberate. Closing real work as "superseded" on thin
evidence destroys it; leaving it listed costs a line in a report.

## The writer that was still manufacturing phantom merges

Batch 1 named the defect but not the file. It is
`runner/approval_merge.py`, and there were two halves to it:

1. **`_integrate()` returned the bare string `"MERGED"`** — no sha. The call site
   wrote `db.update("tasks", …, {"state": result})` directly. That produces a MERGED
   row with `artifact_commit` NULL, which is the exact shape the 2026-08-04 audit
   defined as a phantom merge.

2. **`_integrate()` only moves a LOCAL ref.** The push to origin is behind
   `ORCH_PUSH_ON_MERGE`, which **defaults to `false`**. So on the default path the
   branch is merged into a local `base`, origin never advances, and the task is
   nonetheless recorded MERGED. The DB and GitHub disagree by construction.

Every other MERGED writer in the fleet — `continuous_merger`, `integration_sweeper`
(both sites), `phantom_recovery`, `quarantine_remediation`, `sweep_reconciler`, and
`merge_train._task_patch` — already routes through `merge_truth`. `approval_merge`
was the one that did not, and it is a live, high-traffic writer. That is a complete
explanation for 20 post-audit phantom merges without needing a second cause.

### The fix

- `_integrate()` now returns `MERGED:<sha>`, matching the existing `PUSHFAIL:<err>`
  convention already used in that return position.
- `_split_result()` splits state from evidence so the raw return string can never
  reach the `state` column. A bare `"MERGED"` still parses, carrying no sha — old
  callers keep working and merge_truth simply treats them as unverifiable.
- The terminal write goes through `merge_truth.guarded_task_update(...)` with
  `artifact_commit` set. Three-valued as everywhere else: reachable → MERGED, not
  reachable → `PHANTOM_UNVERIFIED` with the reason, infra error → **write nothing**
  and leave the card for the next cycle. The approvals card is stamped with the
  state that was actually applied, not the one that was hoped for.

`ops/tests/` and `runner/tests/test_approval_merge_evidence.py` cover the split
(including `None`/empty fail-soft), `merged_sha` failure paths, and that a
successful integration returns its sha.

**Also fixed:** `test_approval_merge_rebase_isolated.py::test_integrate_diverged_
branch_calls_rebase_isolated` was already red on master — its `subprocess.run` mock
supplied one result for the two git calls that precede the rebase decision and died
on `StopIteration`. Unrelated to what it asserts; now green. Full file: 64 passed.

## What was deliberately NOT done

- **No sweep.** Batch 1 said not to run batches 2..N as a bulk pass, and nothing here
  requeues 124 branches. That shape is `M4_bulk_resolved_sweep`, which manufactured
  3,765 phantom merges.
- **No branch merged to master, no gate bypassed, no state marked MERGED.**
- **No branch closed as superseded**, because zero of them met the evidence bar.

## Recommended next step

The rate is fine; the arrival rate is the problem. Two things, in order:

1. **Re-run the reconciler now that the leak is closed.**
   `merge_truth.reconcile()` is read-only and will say how many existing MERGED rows
   are actually reachable. With `approval_merge` fixed, that number should stop
   getting worse — which is the only real proof this fix landed.
2. **Look at `chatgpt-local-reconcile-*` before anyone budgets against 276k lines.**
   8 branches, 45% of the total, hours old, with two identical-sized tips. Either it
   is real work that needs a lane, or it is a loop generating branches faster than
   the train can drain them — and those two call for opposite responses.

## Artifacts

- `ops/stranded-branches-20260812.md` — full 194-branch inventory (this pass)
- `ops/stranded-branches-20260806.md` — batch 1 inventory, preserved unmodified
- `ops/stranded_branch_inventory.py` — read-only inventory generator (unchanged)
- `ops/stranded_recovery_queue.py` — batched requeue (unchanged, not run this pass)
- `runner/approval_merge.py` — the phantom-merge fix
- `runner/tests/test_approval_merge_evidence.py` — tests for it
