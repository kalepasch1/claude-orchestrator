# Recovery plan — `backlog-batch-beethoven-63cf995`

**Task:** `backlog-batch-beethoven-63cf995-inventory-clean-environment`
**Date:** 2026-08-06

The task has two halves. The inventory and plan are delivered below. The
"main branch CI green" half **cannot be certified from this task**, and section 1 says
exactly why rather than claiming otherwise.

---

## 1. Environment state, measured

### 1a. On `origin/master`, the test command does not run at all

```
$ python3 -m pytest runner/tests/ -q
INTERNALERROR>   File "runner/tests/test_20260806_session_fixes.py", line 313, in <module>
INTERNALERROR>     sys.exit(0 if ok == len(RESULTS) else 1)
INTERNALERROR> SystemExit: 0
no tests ran in 17.30s
```

Zero tests run, so "main CI green" is not a measurable claim on master today. Cause:
`test_20260806_session_fixes.py` is a standalone verification *script*, not a pytest
module — it does its work at import time and ends in `sys.exit()`. Because it is named
`test_*.py`, pytest imports it during **collection** and the `SystemExit` propagates as
`INTERNALERROR`, aborting collection for all 492 test files.

**This is already fixed, on an unmerged branch.** Sibling task
`improve-value-aware-test-routing-early-exit-r-slice-3-fix-test-command` shipped
`e5557d6a`, which adds a module-level collection guard there and replaces a hard
`from runner import breach_remediation` with `pytest.importorskip`. With that branch
checked out, collection succeeds: **8,330 tests collected in 8.26s, zero collection
errors.** Re-fixing it here would duplicate that commit, so this plan is branched *on top
of* it instead.

### 1b. With collection fixed, the suite stalls partway through

Running the full suite on `e5557d6a` reached ~13% and then stopped making progress; it
had to be killed. Failures visible up to that point were sparse (roughly 15 `F` marks in
the first ~950 tests) and no `FAILED`/`ERROR` summary lines were emitted, because pytest
prints those only at the end.

So there are **two** blockers between here and a green main, and they are sequential:

| # | Blocker | Status |
|---|---|---|
| 1 | Collection aborts on master | Fixed on `e5557d6a`, **needs merging** |
| 2 | Suite stalls mid-run (likely a test doing real network/DB I/O with no timeout) | **Open** — needs `pytest-timeout` or the offending test isolated |

**Recommended first action:** merge `e5557d6a`, then re-run with a per-test timeout
(`--timeout=60`) to identify the hanging test by name. Until blocker 2 is resolved, no
one can produce a trustworthy pass/fail number for this repo, which makes every
"acceptance: tests pass" task in the queue unverifiable. That makes it the highest-value
fix available and it is not this task's scope.

### 1c. A third, quieter blocker

Agent worktrees do not inherit untracked-but-required local files. `runner/.env` is
untracked, so a fresh worktree fails 7 tests with
`RuntimeError: set SUPABASE_URL and SUPABASE_SERVICE_KEY`; symlinking it takes the same
selection to 53/53. Any CI or agent run that does not carry `.env` will report failures
that have nothing to do with the code. See `docs/node-modules-install-failure-rca.md`.

---

## 2. Inventory of the collapsed and derived tasks

The batch absorbed 5 `dropbox-prompt-merged-diff-memory-system-task-spec-*` tasks
(groups 9 and 13) and then spawned its own sub-tree. Current state of all 19 rows in the
family:

### Already resolved — no recovery needed

| Task | State | Evidence |
|---|---|---|
| `backlog-batch-beethoven-63cf995` (parent) | DONE | Group-13 frontmatter pipeline (`parse_frontmatter_and_body`, `process_directory_of_files`) shipped |
| `…-recover-convention-conformance-lints` | MERGED | already in `orchestrator/dev` @ `f7a04d04` |
| `…-convention-conformance-lints-run-build-tests` | SUPERSEDED | the lints are already on master (`f7a04d04`, `runner/tools/lint_conventio…`) |
| `…-recover-merged-diff-memory` | SUPERSEDED | `origin/agent/merged-diff-memory` merged into master; suites green |
| `…-merged-diff-memory-implement-minimal-merged-diff` | DONE | implemented against `test_merged_diff_memory_spec.py` as the spec |
| `…-pinned-express-lane` | DONE | found `express_lane` was dead code twice; fixed |

**Recommended action: none.** Six of the nineteen are genuinely finished.

### Still queued — recommended actions

| Task | State | Recommended action |
|---|---|---|
| `…-convention-conformance-lints-add-new-test` | QUEUED | **Proceed.** Parent lints are on master, so a test can be written against real code. |
| `…-convention-conformance-lints-identify-owner-modu` | QUEUED (attempt 1) | **Mark SUPERSEDED.** The owner is already known and shipped: `runner/tools/lint_conventio…` @ `f7a04d04`. Re-locating it is redundant. |
| `…-merged-diff-memory-investigate-prior-attempt-and` | QUEUED | **Mark SUPERSEDED.** The prior attempt is identified: `origin/agent/merged-diff-memory`, merged. Nothing left to investigate. |
| `…-merged-diff-memory-add-test-and-validate-full-bu` | QUEUED | **Blocked on blocker 2.** "Validate full build" cannot be satisfied while the suite stalls. Add the test; drop the full-build clause. Note `runner/tests/test_merged_diff_memory.py` carries 13 pre-existing collection errors on master — it targets functions (`extract_rules`, `save_to_memory`, `prune_old_entries`) that `runner/merged_diff_memory.py` does not define, so that suite tests a module which no longer exists in that shape. Fix or retire it first. |
| `…-recover-pinned-express-lane` | QUEUED | **Mark SUPERSEDED.** Sibling `…-pinned-express-lane` is DONE and found the module was dead code; there is nothing to recover. |
| `…-integrate-all-recovered` | QUEUED | **Hold.** Integration is the merge train's job, and it should not run while blocker 2 makes test results untrustworthy. Re-queue after blockers 1–2 clear. |
| `backlog-batch-beethoven-e8afcee-*` (4 rows) | QUEUED | **De-duplicate.** All four are explicitly `dedup: waits on 'backlog-batch-beethoven-63cf995-*' (near-duplicate) to reuse result`. When the `63cf995` sibling resolves, close the `e8afcee` twin with the same verdict instead of executing it. That is 4 of 19 rows that are pure duplication. |

### Decomposed shells

`…-convention-conformance-lints` and `…-merged-diff-memory` are DECOMPOSED parents; they
need no action of their own and will close when their children do. The five collapsed
`dropbox-prompt-…group-9/13` rows are likewise DECOMPOSED into the parent.

---

## 3. Summary

Nineteen rows. Six finished, four are self-declared duplicates, four should be marked
SUPERSEDED against evidence already in the repo, one can proceed now, and two are blocked
on a repo-wide problem — the test command — that is outside this batch entirely.

**One rows-to-work ratio worth stating plainly: of 19 tasks, 1 has real remaining work
that is not blocked.** The rest are duplication, already-done, or waiting on the suite.

**Ordered recommendation:**

1. Merge `e5557d6a` (collection fix) — unblocks measurement for the entire repo.
2. Re-run with `--timeout=60`, name the hanging test, fix or skip it.
3. Carry untracked local files (`runner/.env`) into agent worktrees.
4. Fix or retire `runner/tests/test_merged_diff_memory.py` (13 errors, tests a module
   shape that no longer exists).
5. Apply the SUPERSEDED/dedup verdicts above — closes 8 of 19 rows with no code written.
6. Only then run `…-integrate-all-recovered`.
