# Root-cause triage: `runner/tests/` failure mode

Task: `improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-inspect-a`.
The step's acceptance is explicitly *inspection*: reproduce the failure, name the files
involved, summarise the root cause, and capture the current failure mode **before** making
functional changes. This is that capture. No source behaviour is changed by this commit.

Measured against `origin/master@5c4eaf2f` on 2026-08-24.

## The command and the current failure mode

```
python -m pytest runner/tests/ -q --timeout=30
```

```
804 failed, 12959 passed, 13 skipped, 15 errors, 13790 collected  (544s)
```

Failures are spread across **131 distinct test files**. The headline number is misleading,
though, and that is the finding that matters: **the failures are not one problem, and a
large share of them are not real.**

## Finding 1 — a large fraction is order-dependent pollution, not broken code

Several of the worst-looking files pass completely when run alone:

| file | in the full run | run in isolation |
|---|---|---|
| `test_prompt_assembler.py` | 35 failed | **35 passed** |
| `test_canary_gemini_response_parse.py` | 31 failed | **31 passed** |
| `test_value_per_token.py` | 16 failed | **16 passed** |
| `test_zombie_reaper_heartbeat.py` | 27 failed | 1 failed / 56 passed |

Same code, same machine, same interpreter — only the neighbours differ. These fail because
something earlier in the session mutates shared process state (module-level singletons,
`os.environ`, monkeypatched module attributes that are never restored) and does not put it
back. `runner/` uses the module-level singleton pattern deliberately and widely, which is
exactly the shape that leaks across tests when a fixture forgets to reset it.

**Consequence for this task:** "fix the failing tests" would, for these files, mean fixing
tests that are already correct. The defect is isolation, not assertion.

## Finding 2 — the genuine failures are overwhelmingly one shape: a missing symbol

The files that *do* fail in isolation nearly all fail identically — the test calls a name
the module does not define:

| file | isolated result | representative error |
|---|---|---|
| `test_counterfactual_replay.py` | 45 failed | `module 'counterfactual_replay' has no attribute 'store_decision'` (also `add_divergence`, `_replay`) |
| `test_scoreboard_history.py` | 18 failed | `module 'scoreboard' has no attribute '_append_history'` |
| `test_orphaned_worktrees.py` | 15 failed | `module 'worktree_gc' has no attribute 'is_orphaned_worktree'` |
| `test_monthly_audit.py` | 23 failed | `module 'self_review' has no attribute '_parse_schedule_table'` |
| `test_relfix_pareto_2080_release_conflict_healing.py` | 33 failed / 8 passed | mixed |
| `test_secret_risk_pool_rework.py` | 22 failed / 33 passed | mixed |
| `test_zombie_reaper_integration.py` | 22 failed / 7 passed | mixed |
| `test_merge_train.py` | 14 failed / 21 passed | mixed |

`AttributeError: module X has no attribute Y` is not a broken implementation — it is a
**test that was merged without its implementation**, or whose implementation was later
reverted or lost. That matches this repo's known history of agent branches being written,
tested green in a worktree, and then never landing (the `recover-missing-branch-*` churn).
The tests are the surviving half of work whose source half is missing.

## Finding 3 — the 15 errors are collection-time, in one file

All 15 are `runner/tests/test_release_on_capacity.py`, failing at setup rather than
assertion. That file should be triaged on its own; a collection error can mask everything
downstream of it in the same module.

## Why this is NOT a "fix the tests until green" job

The three classes need opposite treatments, and applying one to another does damage:

1. **Order-dependent (Finding 1)** — fix the *fixtures*: reset the singleton/env after each
   test. Touching the assertions here would weaken tests that are correct.
2. **Missing symbol (Finding 2)** — the right move is to find the implementation
   (unmerged agent branch, rescue ref, merged-diff library) and land it. Writing a stub
   named `store_decision` to make the import resolve would produce a green suite that
   tests nothing — the worst possible outcome, because it also destroys the evidence that
   the implementation is missing.
3. **Collection errors (Finding 3)** — a setup bug, independent of both.

## Recommended sequencing for the follow-up step

1. Quantify the split precisely: run each of the 131 files in isolation and record
   pass/fail. Everything that passes alone goes in the pollution bucket.
2. For the pollution bucket, find the leaking module state. Start with the fixtures that
   monkeypatch module attributes without restoring them; `-p no:randomly` and bisecting the
   file order will name the polluter cheaply.
3. For each missing symbol, search `origin/agent/*` and `refs/orch-rescue/*` for the
   implementation **before** writing anything. Several of this repo's "missing" branches
   are intact on origin and merely unmerged.
4. Do not treat "804 → 0" as a single deliverable. It is at least three, and only one of
   them is a code fix.

## Reproduction

```bash
# full run (about 9 minutes)
python -m pytest runner/tests/ -q --timeout=30

# the isolation check that separates the two classes
python -m pytest runner/tests/test_prompt_assembler.py -q      # 35 passed
python -m pytest runner/tests/test_counterfactual_replay.py -q # 45 failed
```
