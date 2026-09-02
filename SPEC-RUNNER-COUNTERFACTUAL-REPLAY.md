---
title: Runner Counterfactual-Replay Implementation (Conflict Recovery)
date: 2026-08-19
status: REFINING
context: Merge conflict recovery from HTTP 409 on commit 07060650; spec was corrupted during conflict resolution. This manual session is fleet-down recovery only.
---

## Problem Statement

The runner daemon (`runner/daemon.py`) currently executes tasks and decisions based on the model state at the time of queuing. When models are updated or new models become available, past tasks that succeeded do not re-evaluate whether the runner would make *different* decisions today.

**Specific need:** Periodically detect decisions/routes the runner would change under newer model logic, and update routing rules and task policies to reflect current model capabilities.

---

## Refined Intent

Implement a **counterfactual-replay module** in the runner that:

1. **Re-evaluates past decisions** (task routing, policy selection) with the current model
2. **Detects divergence:** identifies where the runner would now route differently
3. **Updates policies/routes:** patches `fleet_config` to reflect new model behavior  
4. **Preserves existing runs:** does not re-execute completed tasks, only updates *future* decision logic
5. **Logs all changes:** full audit trail for observability

---

## Scope & File Locations

**Primary owner module:** `runner/daemon.py` (or new `runner/counterfactual.py` if extracted)

**Related files to inspect/modify:**
- `runner/decision_engine.py` — where routing/policy decisions are made
- `fleet_control.py` — the centralized gateway for fleet config changes (use this for policy updates)
- `runner/tests/test_counterfactual_replay.py` — new test suite (created this session)
- `.preopt_cache/` — decision history cache used for replay source data

**Configuration:** all replay tuning must use `ORCH_RUNNER_REPLAY_*` env vars, never hardcoded values

---

## What "Counterfactual-Replay" Means (Resolved)

**Definition:** Re-run the decision logic from past task queue entries through the current decision engine (same entry, new model inference) to determine if the runner would route/prioritize differently today.

**NOT:** re-executing the tasks themselves or running model inference in isolation.

**Scope of re-evaluation:**
- Task routing decisions (which queue/machine)  
- Priority/retry policy selection
- Policy route choices based on task attributes

---

## Past Decisions/Tasks Scope (Resolved)

**Replay this window:**
- Tasks queued in the last 7 days (configurable via `ORCH_RUNNER_REPLAY_LOOKBACK_DAYS`)
- Only completed or terminal tasks (no in-flight tasks)
- Filtered by task type (initially: `job_type in ['build', 'test', 'deploy']`)

**Audit trail:** log each task replayed, original decision, new decision, and whether they diverge

---

## Policies/Routes to Update (Resolved)

**Scope:** configuration keys in `fleet_config` table matching pattern `ORCH_RUNNER_ROUTE_*` or `ORCH_RUNNER_POLICY_*`

**Update mechanism:** use `fleet_control.apply_config_batch()` to push changes atomically; include version/timestamp for conflict detection

**Preservation rule:** do not modify `ORCH_*` keys containing `SECRET`, `PASSWORD`, or `TOKEN`

---

## Acceptance Criteria (Explicit)

### 1. Functional Requirements
- [ ] Counterfactual replay module loads task history from `.preopt_cache/` without errors
- [ ] Decision engine is re-invoked on each past task with current model state
- [ ] Divergence detection correctly identifies >= 1 case where old decision ≠ new decision
- [ ] Policy updates are applied via `fleet_control.apply_config_batch()` (never direct DB writes)
- [ ] No completed/terminal tasks are re-executed; logic only updates future routing

### 2. Testing Requirements
- [ ] **Unit tests** (`runner/tests/test_counterfactual_replay.py`):
  - Replay a mock task history, verify old vs. new decisions
  - Test divergence detection (at least 1 task changes route, 1 stays same)
  - Verify no tasks are re-queued during replay
  - Test `ORCH_RUNNER_REPLAY_*` env var parsing (lookback window, task filters)
  - Test `fleet_control` config batch application (success & conflict scenarios)
  - Edge cases: empty history, all decisions identical, malformed cache entries
  
- [ ] **Integration tests**:
  - Replay against actual `.preopt_cache/` entries from this session
  - Verify `fleet_config` table updated with new policies
  - Verify no side effects on running tasks

### 3. Code Quality
- [ ] All `ORCH_*` config keys used, no hardcoded values
- [ ] Fail-soft error handling: missing cache files → empty result, bad config → log and skip
- [ ] Module-level functions delegate to singleton instance (if extracted to new module)
- [ ] Load-bearing comments only: explain *why* a divergence matters, not what the line does
- [ ] No silent broad exceptions; all `except Exception` must log diagnostics

### 4. Merge Criteria
- [ ] Smallest mergeable diff (no refactor of unrelated code)
- [ ] Preserves all existing runner behavior (no behavior changes, only new replay feature)
- [ ] All tests pass locally and in CI
- [ ] Commit authored as `kalepasch1 <kalepasch@gmail.com>` (repo policy)

---

## Implementation Plan

### Phase 1: Locate & Analyze
1. Read `runner/daemon.py` to understand task queue structure and decision flow
2. Inspect `decision_engine.py` to find decision-making entry points
3. Review `.preopt_cache/` structure to understand history format
4. Examine `fleet_control.py` config batch API

### Phase 2: Implement Counterfactual Module
1. Create or extend `runner/counterfactual.py`:
   - `load_task_history(lookback_days, task_filters)` → list of past task decisions
   - `replay_decisions(task_list, decision_engine)` → (original_decision, new_decision) pairs
   - `detect_divergence(decisions)` → list of (task_id, old_decision, new_decision)
   - `apply_policy_updates(divergences, fleet_control)` → update `fleet_config`

2. Add env var configuration:
   - `ORCH_RUNNER_REPLAY_LOOKBACK_DAYS=7` (default)
   - `ORCH_RUNNER_REPLAY_TASK_TYPES=build,test,deploy` (default)
   - `ORCH_RUNNER_REPLAY_ENABLED=true` (kill-switch)

3. Integrate into `daemon.py` as a periodic background task (e.g., daily)

### Phase 3: Test & Validate
1. Write `runner/tests/test_counterfactual_replay.py` (20+ test cases per CLAUDE.md convention)
2. Run local tests with mock cache data
3. Integration test against actual `.preopt_cache/` from this repo
4. Verify `fleet_config` updates are applied correctly

### Phase 4: Commit & Recover
1. Create new branch: `runner/counterfactual-replay-<hash>`
2. Commit with message:
   ```
   Implement counterfactual-replay: detect model divergence in past decisions
   
   Re-evaluates task routing/policy decisions from the last 7 days using current
   model state, detects divergence, and updates fleet_config policies atomically.
   Preserves existing task execution (replay-only, no re-queueing).
   
   - Load task history from .preopt_cache/ with configurable lookback
   - Detect decisions that would change under new model
   - Apply policy updates via fleet_control.apply_config_batch()
   - Comprehensive test suite (20+ cases) covering normal/edge cases
   
   Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>
   ```
3. Push to remote and open PR for review

---

## Source Reference Resolution

**Original:** `6096aa2b-8eaf-4622-b65d-a5f8e22456b6/patch-template-relfix-racefeed-07060650-commit-package-files`

**Interpretation:** This was likely a stashed patch from commit `07060650` that was lost during the merge conflict. The patch attempted to template a fix for race-feed config sync. **Action:** Recover intent from the failure context (409 conflict) and implement fresh based on above spec; do not attempt to restore the patch verbatim (it corrupted during conflict).

---

## Failure Context (Recovered)

**What happened:** Merge conflict on `runner/daemon.py` when pulling updated decision logic. Conflict markers corrupted the spec intent section. Runner process crashed with `HTTP Error 409: Conflict` when attempting to apply competing config changes from two machines.

**Why manual session:** This is fleet-down recovery — the fleet cannot self-queue work until the conflict is resolved and a working baseline restored.

**Next step after manual session:** Once working baseline is restored, drop `PROMPT-RUNNER-COUNTERFACTUAL-REPLAY.md` into `intake/` for routine operator workflow (parallel execution via intake_watcher).

---

## Confidence Notes

- **High confidence (0.9)** on the counterfactual-replay feature intent and scope
- **High confidence (0.85)** on file locations (verified runner/ structure exists)
- **Medium confidence (0.7)** on exact decision-engine integration points (need to read the code)
- **Medium-high confidence (0.8)** on acceptance criteria (based on CLAUDE.md conventions)

---

## Change Summary

| Ambiguity | Resolution |
|-----------|-----------|
| What is "counterfactual-replay"? | Re-run past task decisions through current model logic; detect routing divergence; update policies. No re-execution. |
| Intent section corrupted | Recovered from failure context: runner crashed on conflicting config writes during merge. |
| "patch-template-relfix-racefeed-*" | Was a stashed patch lost in conflict. Implement fresh from spec; do not recover patch. |
| "detect where it would now choose differently" | Task routing/policy selection decisions: which queue, which priority, which retry logic. |
| Which past decisions/tasks? | Last 7 days, completed/terminal tasks, filtered by type (build/test/deploy). Configurable via env vars. |
| Which policies/routes? | `ORCH_RUNNER_ROUTE_*` and `ORCH_RUNNER_POLICY_*` config keys; applied via `fleet_control.apply_config_batch()`. |
| Smallest mergeable diff? | New `runner/counterfactual.py` + tests + minimal integration into `daemon.py` (one periodic call). |
| Which tests must pass? | Unit suite (20+ cases) + integration tests; all existing runner tests still pass. |
