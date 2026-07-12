# Orchestrator Hardening — Tier 1 (self-executable by fleet)

These improvements target the runner's own codebase. Each task is a single-file change
with clear proof criteria. All are additive — no existing behavior changes.

---

## GLOBAL CONTEXT

- Target repo: `claude-orchestrator` (this repo)
- All changes are in `runner/` unless noted
- Follow CLAUDE.md conventions: fail-soft, env-var config, thread-safe singletons
- Every task must include tests in `runner/tests/`

## GLOBAL GUARDRAILS

- **Additive only.** Do not change control flow in existing error handlers.
- **No new dependencies.** Use stdlib only (logging, threading, concurrent.futures).
- **Proof or it isn't done.** Each task names a command that must pass green.

---

### T1 — Add structured logging module  [model: haiku]
Goal: replace bare `print()` with a stdlib `logging` logger across the runner.
Scope: create `runner/log.py` with a `get(name)` factory. Convert `runner.py` print
statements to use it. Include host, timestamp, level, and logger name in format.
Do NOT convert other files yet — just runner.py and log.py in this task.
Steps: (1) create `runner/log.py` with configurable LOG_LEVEL env var. (2) add
`_log = log.get("runner")` at top of `runner.py`. (3) convert the 10 most important
`print()` calls in the claim loop and task dispatch to `_log.info()`. Leave hook
prints for T2. (4) add `runner/tests/test_log.py` with basic tests.
Proof: `python3 -m pytest runner/tests/test_log.py -v` green; `grep -c 'print(' runner/runner.py`
decreases by at least 10.

### T2 — Surface swallowed hook errors  [model: haiku]  [depends: T1]
Goal: add debug logging to all `except Exception: pass` blocks in runner.py hooks.
Scope: `runner/runner.py` pre-hooks (lines ~527–902) and post-hooks (lines ~1386–1544).
Steps: (1) for each `except Exception: pass` block, replace `pass` with
`_log.debug("hook %s failed: %s", hook_name, e, exc_info=True)`. (2) do NOT change
control flow — still swallow the exception. (3) add a test that mocks a failing hook
and asserts it logs but doesn't raise.
Proof: `grep -c 'except.*pass' runner/runner.py` drops to near-zero;
`python3 -m pytest runner/tests/ -k hook -v` green.

### T3 — Parallelize independent pre-hooks  [model: sonnet]  [depends: T2]
Goal: run independent pre-hooks concurrently using ThreadPoolExecutor.
Scope: `runner/runner.py` pre-hook pipeline (lines ~680–902).
Steps: (1) identify hooks with no data dependencies on each other (most of them).
(2) group into dependency tiers. (3) run each tier with ThreadPoolExecutor(max_workers=4).
(4) use the existing `parallel_gates` pattern as the template. (5) each hook still
fail-soft with logging from T2. (6) add timing: log total pre-hook wall time before
and after parallelization.
Proof: a test that mocks 5 hooks with 100ms sleep each, asserts total wall time < 300ms
(not 500ms); `python3 -m pytest runner/tests/ -v` all green.

### T4 — Cache done-slug set in claim_task  [model: haiku]
Goal: stop fetching ALL completed task slugs on every claim cycle.
Scope: `runner/db.py` `claim_task()` function.
Steps: (1) add a module-level `_done_cache = {"slugs": set(), "ts": 0}` with 60s TTL.
(2) on cache miss, fetch with `limit=10000` instead of unbounded. (3) on cache hit,
return cached set. (4) add `invalidate_done_cache()` for tests. (5) add a test.
Proof: `python3 -m pytest runner/tests/test_claim_task_order.py -v` green; new test
asserts cache hit returns same set without DB call.

### T5 — SLO controller fail-safe fix  [model: haiku]
Goal: SLO checks return UNKNOWN (not GREEN) on measurement failure.
Scope: `runner/slo_controller.py` — all check functions.
Steps: (1) replace `return {"ok": True, ...}` in except blocks with
`return {"ok": None, "state": "UNKNOWN", "reason": str(e)}`. (2) in the
remediation loop, skip UNKNOWN SLOs (don't trigger actions). (3) add
`runner/tests/test_slo_controller.py` with tests for: normal GREEN, threshold
breach RED, DB failure UNKNOWN.
Proof: `python3 -m pytest runner/tests/test_slo_controller.py -v` green.

### T6 — Fix datetime.utcnow() deprecation  [model: haiku]
Goal: replace all `datetime.utcnow()` with `datetime.now(datetime.timezone.utc)`.
Scope: `runner/slo_controller.py`, `runner/cost_intelligence.py`, `runner/merge_cycle.py`.
Steps: (1) grep for `utcnow()` across runner/*.py. (2) replace each with
`datetime.now(datetime.timezone.utc)`. (3) also fix any `.replace("+00:00", "")`
hacks in timestamp parsing — use proper `fromisoformat()` instead.
Proof: `grep -r 'utcnow' runner/*.py` returns 0 results; existing tests still green.

### T7 — Fix resource_governor file handle leaks  [model: haiku]
Goal: wrap bare `open()` calls in `with` statements.
Scope: `runner/resource_governor.py` lines ~389–398 (`set_throttle`, `current_limit`).
Also check `runner/planner.py` line ~56 for the same pattern.
Steps: (1) grep for `open(` without `with` in runner/*.py. (2) wrap each in
`with open(...) as f:`. (3) verify no behavior change.
Proof: `grep -Pn 'open\(' runner/resource_governor.py runner/planner.py | grep -v 'with '`
returns 0; existing tests green.

### T8 — Fix task_slicer parent-before-children atomicity  [model: haiku]
Goal: insert child slices before flipping parent to DECOMPOSED.
Scope: `runner/task_slicer.py` `pre_agent_hook()`.
Steps: (1) move the parent state flip (currently ~line 163) to AFTER all child
inserts succeed (~line 190). (2) if any child insert fails, leave parent in
original state (QUEUED) so it can be retried. (3) update existing tests.
Proof: `python3 -m pytest runner/tests/test_task_slicer.py -v` green; a new test
that mocks a child insert failure asserts parent stays QUEUED.

### T9 — Intake watcher retry cap  [model: haiku]
Goal: stop infinite retries on permanently-malformed intake files.
Scope: `runner/intake_watcher.py`.
Steps: (1) add a module-level `_retry_counts: dict[str, int]` tracking attempts
per file path. (2) on decomposition failure, increment counter. (3) if counter > 3,
move file to `intake/failed/` and log a warning. (4) add a test.
Proof: `python3 -m pytest runner/tests/test_intake_dropbox.py -v` green; new test
asserts 4th failure moves file to `intake/failed/`.

### T10 — Fix dir() anti-pattern in runner.py  [model: haiku]
Goal: replace `'_plan' in dir()` checks with proper sentinel pattern.
Scope: `runner/runner.py` (~18 occurrences).
Steps: (1) at the top of `run_task()`, initialize all optional variables to `None`:
`_plan = _diff = _mesh = ... = None`. (2) replace every `if '_plan' in dir()` with
`if _plan is not None`. (3) same for all other `in dir()` checks.
Proof: `grep -c "in dir()" runner/runner.py` returns 0; full test suite green.
