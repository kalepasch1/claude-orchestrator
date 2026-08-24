# Recovery plan — beethoven/claude-orchestrator

Produced by the `inventory-clean-environment` task. Everything below was measured on this
checkout, not inferred: each claim names the command that produced it.

## 1. What was actually broken on main

The task assumed a small set of failures. The real picture, measured:

| Finding | Evidence | Status |
| --- | --- | --- |
| **sys.modules pollution across test modules** | `runner/tests/conftest.py` restored 5 modules; a source scan finds ~28 faked. `runner/tests/test_value_per_token.py` failed with `cannot import name 'revenue_keywords' from 'model_policy' (unknown location)` in a suite run and passed in isolation | **FIXED HERE** |
| Conflict markers committed to master in 4 hisanta files | `import hisanta` raised SyntaxError; 3 test modules uncollectable | FIXED — `agent/orch-config-consumption-re-run-full-build-test-in-clean-state-to` (`9e0a21d8`) |
| `runner/test_economic_scheduler.py` 12 failures | cost read from a field the queue never sets; kind weight hardcoded to 1.0; `apply_routing` no-op'd behind a flag | FIXED — `agent/backlog-batch-beethoven-a86bb21-...` (`f3f57454`) |
| `tests/test_db_connectivity.py` 6 failures | mocked `db.execute`, which does not exist; every assertion swallowed by a bare `except` | FIXED — `agent/improve-upgrade-to-a-high-performance-database-slice-5` (`fe4ea30a`) |
| `tests/test_validate_canary_divergence.py` 1 failure | pinned substring matching that was deliberately removed on 2026-08-13 | FIXED — `agent/canary-xai-6-adapt-proven-diffs` (`46545afb`) |

### The fix in this commit

`runner/tests/conftest.py` restored a **hand-written list** of five modules, with a
comment stating that every faked module must be listed "or it leaks into every module
imported afterwards". The suite fakes roughly twenty-eight. The list had not kept up, and
`runner/tests/test_conftest_module_isolation.py` — the guard written to catch exactly this
— had itself been failing.

Rather than extend a list that has already proven unmaintainable, conftest now **evicts**
any synthetic stub that shadows a real `runner/<name>.py`. Eviction restores just as
effectively (the next import loads from disk), needs no list, and cannot fall out of date.
Names with no real module behind them are declared in `SYNTHETIC_ONLY`, so an
un-restorable fake is a recorded decision rather than a silent omission.

Measured on an identical selection
(`pytest runner/tests -k "isolation or value_per_token or model_routing or model_policy"`):

| | failed | passed |
| --- | --- | --- |
| master | 34 | 108 |
| this branch | **7** | **138** |

## 2. Recovery status of the queued work

Every task inspected in this pass resolved to one of three states. None needed a branch
reconstructed — the branches were present or the work was already on master.

| State | Meaning | Action |
| --- | --- | --- |
| `DONE` + `artifact_commit` | code committed and pushed to `agent/<slug>` | none — merge train picks it up |
| `SUPERSEDED` | the described work is already on master, verified by file+line | none — do not re-run |
| `BLOCKED` | no code target in this repo (e.g. a Maven/Java spec, or a missing input file) | operator re-scope or re-point at the right repo |

## 3. Known-remaining failures (not caused by, and not fixed by, this branch)

- `runner/tests/test_model_routing.py` — 3 model-catalog/deprecated-env failures.
- `runner/tests/test_worktree_isolation.py::test_repo_lock_fails_closed_when_lock_directory_is_unavailable`.
- `runner/tests/test_value_per_token.py::TestChooseValueRouting` / `TestAnalysisIncludes…`
  — these fail on master too and are a separate defect from the import pollution.

These are real and worth their own tasks. They are listed rather than silently folded into
this change, because a branch that claims "main is green" while quietly widening its scope
is how the next audit ends up not trusting any of it.

## 4. Standing recommendation

The merge gate runs the whole suite in one process. Any test that writes
`sys.modules[...]` at import time can therefore change the outcome of a test that runs
after it, and the failure surfaces in the *victim*, far from the cause. The eviction hook
closes the current instance; `test_conftest_module_isolation.py` now fails loudly if a new
un-restorable fake is introduced.
