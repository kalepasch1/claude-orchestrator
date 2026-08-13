# Stranded-branch recovery — batch 3 (reconcile re-run + the `chatgpt-local-reconcile` verdict)

2026-08-12. Batch 2 (`ops/stranded-recovery-batch-2-report.md`) closed with two instructions,
in order. This slice executes both, and both changed the picture.

> 1. **Re-run the reconciler now that the leak is closed.** […] With `approval_merge` fixed,
>    that number should stop getting worse — which is the only real proof this fix landed.

> 2. **Look at `chatgpt-local-reconcile-*` before anyone budgets against 276k lines.** 8 branches,
>    45% of the total […] Either it is real work that needs a lane, or it is a loop generating
>    branches faster than the train can drain them — and those two call for opposite responses.

No sweep was run. No branch was merged, no gate bypassed, and nothing was marked MERGED.

---

## 1. Reconcile re-run — the `approval_merge` fix held, and a *different* writer is leaking

`merge_truth.reconcile()` could not be run in-process from this session (no credentials are
available to it here, and fetching them is prohibited), so the same question was answered
directly against the task table: how many `MERGED` rows carry an `artifact_commit` that
`merge_truth` could verify, and when were the unverifiable ones written.

| project | MERGED total | MERGED with no evidence | MERGED since 08-12 | …of those, no evidence | PHANTOM_UNVERIFIED |
|---|---:|---:|---:|---:|---:|
| beethoven | 1318 | 1144 | 4 | **0** | 4711 |
| tomorrow | 891 | 705 | 0 | 0 | 1220 |
| **apparently** | 638 | 208 | 283 | **208** | 5 |
| pareto-2080 | 325 | 275 | 0 | 0 | 786 |
| smarter | 239 | 198 | 0 | 0 | 1040 |
| darwn | 185 | 170 | 0 | 0 | 291 |

**The fix landed.** Every `MERGED` row beethoven has written since the `approval_merge` repair
carries a verifiable `artifact_commit`. The historical 1,144 evidence-less rows are pre-fix
residue, and `PHANTOM_UNVERIFIED` is doing its job — 4,711 rows that a naive writer would have
recorded as merges are instead correctly flagged as unproven.

**But a second writer is leaking, in a different repo and a different shape.** All 208 of
`apparently`'s evidence-less `MERGED` rows were written *after* the fix, and they share one
timestamp:

```
distinct_timestamps = 1
rows_affected       = 208
ts                  = 2026-08-12 00:31:55.133851+00
```

208 rows, identical to the microsecond. That is not 208 merge decisions; it is **one bulk
UPDATE**. It is the `M4_bulk_resolved_sweep` shape that batches 1 and 2 both warned against, and
it happened while this recovery effort was in flight. The notes are self-describing:

| note prefix | rows |
|---|---:|
| `zero-diff completion — no code to merge` | 134 |
| `bulk-drain: already integrated in base branch` | 48 |
| `train: already integrated in orchestrator/dev` | 13 |
| `train: already integrated in master` | 10 |
| other (single rows) | 3 |

The rationale may well be right for many of them — "already integrated in master" is a real
category. That is not the defect. The defect is that **not one of the 208 carries the sha that
would let anyone check**, so all 208 are indistinguishable from phantoms by construction, and
`merge_truth` will never be able to confirm or refute them.

This is worse than the `approval_merge` bug it followed, because `approval_merge` produced
phantoms one at a time as a side effect. This produced 208 deliberately, in a single statement,
from a script that had the reachability answer in hand and did not record it.

**Needs the operator.** Whatever ran at `2026-08-12 00:31:55Z` against `apparently` should route
through `merge_truth.guarded_task_update()` like every other writer, or stop writing `MERGED`.
Until it is identified, the 208 rows should not be trusted and should not be re-swept — 
re-stamping them would only add a second unverifiable layer.

---

## 2. `chatgpt-local-reconcile-*` — neither reading was right

Batch 2 posed it as a binary: real work needing a lane, or a runaway loop. It is a **cumulative
loop that also contains real work**, and per-branch line counts cannot see the difference —
because each run re-commits its predecessors' output, so the same blob is counted once per
branch that carries it.

`ops/stranded_branch_families.py` (new, read-only) counts each unique `(path, blob-sha)` exactly
once:

| | value |
|---|---:|
| branches | 8 |
| naive added lines (what batch 2 saw) | **132,318** |
| unique added lines | 53,632 |
| **recounted** (same bytes, counted again) | **78,686** |
| of the unique lines: machine-generated ledger JSON | 44,154 |
| of the unique lines: **authored** | **9,478** |

So the family is **9,478 lines of authored work, not 132,318** — an overstatement of roughly
14×. Two thirds of the headline number is the same four `docs/recovery-ledger/*.json` files
being re-committed by each successive run, and most of the remainder is those ledgers counted
once. Nobody should budget a lane against 132k lines here.

The authored remainder is genuinely worth recovering, and it is ordinary code:

| branch | authored content |
|---|---|
| `…-7b6f925e1e7a` | `runner/release_train.py` paused-host guard + test + migration (18 files) |
| `…-8e45bfd2cc58` | `runner/local_evidence_reconciler.py` + test |
| `…-a92ff481c0ba` | `runner/reconcile_followup_queue.py` + test |
| `…-21bc760c4d1d` | 94 `.recovery-intent-*.txt` files (20 lines total) |
| `…-286879fa5fe4` | `scripts/reconcile-evidence.mjs` (485) + 4 ledger JSONs |

**One branch is provably closable today.** `…-44d6bb63e4fc` and `…-286879fa5fe4` point at the
*identical* commit `a71e47e9`. Same tip, two slugs. Closing the duplicate loses nothing, and the
evidence is a sha comparison rather than a judgement call.

`…-6e398b6bdfef` and `…-d64eac25eb52` look subsumed — every file they touch is byte-identical
inside `a71e47e9` **except `docs/recovery-ledger/README.md`**, where they carry an earlier
72-line version against the later 78-line one. The tool therefore classifies them `distinct`,
not `subsumed`, and it is right to: closing on path overlap while ignoring a content difference
is precisely how real work gets destroyed. They are cheap for an operator to confirm by eye, but
this slice will not assert it.

---

## 3. Inventory re-measure

Same read-only tool, same exclusions, measured against `origin/master`:

| | 08-06 (batch 1) | 08-12 (batch 2) | now (batch 3) |
|---|---:|---:|---:|
| `agent/*` branches on origin | 482 | 962 | **967** |
| already merged into master | 363 | 768 | **761** |
| stranded | 119 | 194 | **206** |
| merge cleanly | 103 | 124 | **141** |
| would conflict | 16 | 70 | **65** |

Hours apart from batch 2, so this is not an independent trend reading — it is a consistency
check, and it is consistent. The clean share improved (124/194 → 141/206) and the conflicting
count did not grow.

Family view of the whole stranded set (full table in the artifacts below):

| family | branches | naive + | unique + | recounted | authored |
|---|---:|---:|---:|---:|---:|
| `chatgpt-local-reconcile` | 8 | 132318 | 53632 | 78686 | 9478 |
| `improve-missing-branch` | 11 | 19498 | 6157 | 13341 | 6157 |
| `dropbox-beethoven-audit` | 25 | 16741 | 13443 | 3298 | 13415 |
| `dropbox-wave-c` | 17 | 6618 | 4241 | 2377 | 4233 |

Across all stranded branches the naive total is **275,119** added lines. Recounting is
concentrated in the loop-shaped families above; `improve-missing-branch` re-counts 68% of its
own total and has 7 provably closable branches. **The stranded backlog is materially smaller
than any line-count summary published so far has implied.**

---

## What was deliberately NOT done

- **No sweep.** Nothing was requeued in bulk. Batches 1 and 2 both said not to, and the
  `apparently` finding above is a live demonstration of why.
- **No branch merged to master, no gate bypassed, no state marked MERGED.**
- **No branch closed as superseded.** One duplicate (`…-44d6bb63e4fc`) meets the evidence bar and
  is *recommended* for closure; this slice does not close it. Every other candidate resolved to
  `distinct`.
- **No task row invented** for any branch whose task is gone.
- **No task state changed by this slice at all.**

## Recommended next step

1. **Identify the writer behind `2026-08-12 00:31:55.133851+00` on `apparently`** and route it
   through `merge_truth.guarded_task_update()`. This is the only item that is actively making
   the problem worse; everything else in this report is inventory.
2. **Close the one proven duplicate** (`agent/chatgpt-local-reconcile-beethoven-44d6bb63e4fc`,
   identical tip to `…-286879fa5fe4`) and give the three authored `chatgpt-local-reconcile`
   branches a normal lane. That is ~9.5k lines, not 132k.
3. **Re-run `ops/stranded_branch_families.py` before any future line-count claim.** Every batch
   so far has quoted naive totals; this pass shows they overstate by up to 14× on the families
   that matter most.

## Artifacts

- `ops/stranded-branches-20260812-slice3.md` — full 206-branch inventory (this pass)
- `ops/stranded_branch_families.py` — new: family/duplicate/subsumption analysis, read-only
- `ops/tests/test_stranded_branch_families.py` — 19 tests
- `ops/stranded_branch_inventory.py` — unchanged, read-only
- `ops/stranded_recovery_queue.py` — unchanged, **not run this pass**
