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

---

# Recovery plan — `backlog-batch-beethoven-e8afcee`

**Task:** `backlog-batch-beethoven-e8afcee-inventory-clean-environment`
**Date:** 2026-08-13
**Branch:** `agent/backlog-batch-beethoven-e8afcee-inventory-clean-environment`

Supersedes nothing; appended alongside the 2026-08-06 section above, which
reached the same conclusion about the "CI green" half. This run went further on
the *why* and lands an actual fix for the largest cause.

---

## 1. What was broken, and what this branch fixes

### Measured baseline on `master` (unmodified)

```
python3 -m pytest tests/ -q --continue-on-collection-errors
14 failed, 1182 passed, 12 errors in 73.11s
```

The **12 errors were collection failures**, not test failures — twelve whole
files never ran:

```
ModuleNotFoundError: No module named 'runner.enqueue'; 'runner' is not a package
ImportError: cannot import name 'prompt_evolver' from 'runner' (.../runner/runner.py)
```

### Root cause

`runner/` **is** a package (`runner/__init__.py` exists) and every one of those
modules imports cleanly on its own:

```
$ python3 -c "import runner.enqueue"      # succeeds
```

The failure is a *name collision*, and it only appears under whole-suite
collection. Modules under `runner/` (and the tests that drive them) do:

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # adds runner/ to sys.path
```

so flat sibling imports (`import db`, `import merged_diff_memory`) resolve.
A side effect is that **`runner/runner.py` becomes importable as a top-level
module named `runner`**. `pytest tests/` collects everything in one process, so
whichever test imports first wins the name. When a test that had pushed
`runner/` onto `sys.path` went first, `sys.modules["runner"]` became the
`runner.py` *module*, and every later `from runner.<x> import ...` failed
because a module has no submodules.

### Fix landed here

`conftest.py` at repo root (new file, 72 lines, no other production code
touched). pytest imports `conftest.py` before any test module, so it binds the
real package into `sys.modules["runner"]` once, up front; later `sys.path`
pushes are then harmless because the name is already taken by the package.

It loads the package **by file location** (`importlib.util.spec_from_file_location`)
rather than by reordering `sys.path`. That distinction was arrived at
empirically — see §3.

### Result

```
python3 -m pytest tests/ -q --continue-on-collection-errors
21 failed, 1207 passed, 0 errors in 50.83s
```

| | master | this branch |
|---|---|---|
| collection errors | 12 | **0** |
| tests actually executed | 1196 | **1228** |
| passing | 1182 | **1207** (+25) |
| failing | 14 | 21 (+7, see §2) |

**No test that passed on master fails here.** The `comm` diff of the two
FAILED lists shows zero entries in the "fixed on master, broken here" column.

---

## 2. The 7 additional failures are revealed, not caused

All seven live in files that **could not be collected at all on master**, or are
order/environment-sensitive. None is a regression introduced by this branch.

| Failure family | Count | Assessment |
|---|---|---|
| `tests/test_prompt_evolver_exploration.py` (3) | 3 | File was one of the 12 that never collected. These assertions have been failing silently since the file was written. **Genuine open bug** — needs a real fix. |
| `tests/test_core_retry_rpcs.py` (3) | 3 | Order-sensitive. This suite monkeypatches **global** `urllib.request.urlopen` via `db.urllib.request.urlopen = ...`. Run in isolation on unmodified `master` it already fails 4/15. Any change to import order perturbs it. **Test-design defect, not a product defect.** |
| `tests/test_cowork_assemble_args.py` (1) | 1 | Shells out to `runner/cowork_assemble.py` with a 30s `subprocess` timeout; that script performs network/DB work. Passes in 1.8s or times out at 30s depending on network. **Flaky by construction.** |

### Recommended follow-ups (not attempted here — out of scope for one task)

1. **`test_core_retry_rpcs.py`** — stop mutating the global `urllib` module.
   Patch the seam on the `db` module object with `unittest.mock.patch.object`
   and a proper context manager so state cannot leak between tests. This is the
   highest-value cleanup: it is currently capable of breaking unrelated suites.
2. **`test_prompt_evolver_exploration.py`** — three real assertion failures in
   the UCB1 arm-selection logic. Now that the file collects, these are visible
   and fixable; treat as a `bugfix` task against `runner/prompt_evolver.py`.
3. **`test_cowork_assemble_args.py`** — mark `@pytest.mark.slow`/network, or
   stub the subprocess, so a cold network does not fail the suite.

### Rejected approach, recorded so it is not retried

Making `runner/__init__.py` lazy (PEP 562 `__getattr__` instead of the eager
`from . import git_diagnostics`) looked attractive — importing a package should
not import `db` and freeze its retry config. **It made things worse: 29 failed.**
Deferring the import splits module identity between top-level `db` and
`runner.db`, so the retry tests patch one object and exercise the other. The
eager import was reverted and is untouched on this branch. If anyone revisits
the `runner/__init__.py` side effect, fix the `db` double-import first.

---

## 3. Inventory of the 11 collapsed queued tasks

Highest-attempt QUEUED beethoven tasks, each checked against `origin` for a
recoverable artefact. `ahead` = commits ahead of `origin/master`;
`merge` = `git merge-tree` conflict probe.

| # | slug | attempt | branch on origin | ahead | files | merge | recommended action |
|---|---|---|---|---|---|---|---|
| 1 | `session-proof-of-work` | 67 | ✅ `435ded84` | 0 | 0 | clean | **SUPERSEDED** — content already in master |
| 2 | `backlog-batch-beethoven-d00ef24-economic-scheduler-revenue-create-revenue-module` | 12 | ❌ none | – | – | – | **re-run from prompt** (no artefact to recover) |
| 3 | `backlog-batch-beethoven-4c9d580-slice-2` | 12 | ✅ `a4e05b0c` | 0 | 0 | clean | **SUPERSEDED** |
| 4 | `remediate-dropbox-mission-legal-radar-v2-...-lega-m` | 11 | ✅ `e3efe2aa` | 0 | 0 | clean | **SUPERSEDED** |
| 5 | `backlog-batch-beethoven-22ee5bc-recover-pinned-exp-slice-3` | 11 | ✅ `b578b67a` | 0 | 0 | clean | **SUPERSEDED** |
| 6 | `remediate-improve-implement-real-time-sync-between-web-and-slice-2-...` | 8 | ❌ none | – | – | – | **re-run from prompt** |
| 7 | `backlog-batch-beethoven-caafadd` | 7 | ❌ none | – | – | – | **re-run from prompt** |
| 8 | `orch-cross-project-depends` | 7 | ✅ `54b96da1` | **1** | **5** | **clean** | **MERGE NOW** — only branch with real recoverable work |
| 9 | `backlog-batch-beethoven-18fa8e4-slice-5` | 6 | ✅ `b578b67a` | 0 | 0 | clean | **SUPERSEDED** (same sha as #5 — duplicate push) |
| 10 | `remediate-improve-value-aware-test-routing-early-exit-r-slice-3-...` | 6 | ❌ none | – | – | – | **re-run from prompt** |
| 11 | `escalate-p1-queue-clearance-no-improvement-20260810-nk73` | 6 | ❌ none | – | – | – | **close** — meta/escalation task, no code target |

### Headline finding

**Only 1 of 11 has recoverable unmerged work.** The dominant failure mode is
not lost code — it is **state drift**:

- **5 tasks (#1, #3, #4, #5, #9)** have branches that are `ahead=0, files=0`.
  Their work is already in `master`, yet they sit `QUEUED` and keep getting
  re-attempted. #5 and #9 point at the *same sha* (`b578b67a`) — one task's
  push was recorded against two slugs. Between them these have burned
  **67 + 12 + 11 + 11 + 6 = 107 attempts** re-doing finished work.
- **5 tasks (#2, #6, #7, #10, #11)** have no branch at all after 6–12 attempts
  each, meaning every attempt failed before push.

### Recommended recovery actions, in order

1. **Merge `agent/orch-cross-project-depends`** (`54b96da1`, 5 files, conflict-free).
   This is the whole recoverable yield.
2. **Bulk-transition #1, #3, #4, #5, #9 → `SUPERSEDED`** with note
   `"branch ahead=0 vs master; work already merged"`. Stops 5 tasks from
   re-claiming forever.
3. **Add an executor pre-flight guard:** before claiming, if
   `origin/agent/<slug>` exists and is `ahead=0` of the base branch, close as
   SUPERSEDED instead of re-running. This class of waste is mechanical and
   entirely preventable — it is the single highest-leverage fix in this report.
4. **Investigate the 5 no-branch tasks as a group.** Five tasks failing 6–12
   times each without ever producing a push is a systemic executor failure, not
   five independent task failures. Pull their `note` history before re-queuing.
5. Work the three test follow-ups in §2.

---

## 4. Acceptance, stated honestly

- ✅ `RECOVERY_PLAN.md` present, with all 11 tasks inventoried, artefact status
  measured against `origin`, and recommended actions.
- ✅ Build/test suite run on the base branch; failures identified **and the
  largest single cause fixed** (12 collection errors → 0, +25 tests recovered).
- ❌ **"main branch CI green" is NOT met and is not claimed.** 21 failures
  remain. 3 are a genuine open bug in the prompt-evolver, 3 are a
  self-inflicted global-state test defect, 1 is network flake, and 14 are the
  pre-existing `master` failures (DB connectivity, env-safety scanners,
  queue-materializer) that require credentials/network this task did not have.
  Certifying green here would be false.
