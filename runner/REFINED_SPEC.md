# Refined Spec: Add `runner/prompt_evolver.py` — UCB1 Bandit over Per-Kind Prompt Templates

**Patch Template:** f4b5aaf6893c  
**Status:** Implemented (see runner/prompt_evolver.py)  
**Date Resolved:** 2026-08-19

---

## Overview

Create a UCB1-based multi-armed bandit module for selecting and evaluating prompt template variants per task kind. The module tracks success rates across templates and uses bandit scoring to balance exploration (trying new templates) with exploitation (using proven templates).

---

## Scope

Create or update exactly two files:
1. **`runner/prompt_evolver.py`** — UCB1 bandit implementation (ALREADY EXISTS; this spec formalizes it)
2. **`runner/tests/test_prompt_evolver.py`** — Unit tests (to be created/updated)

Modify no other files. Do not touch `runner.py`, `.claude/settings.local.json`, migration files, or DB schema definitions.

---

## `runner/prompt_evolver.py`

### Module-Level Architecture

**RESOLVED AMBIGUITY #2:** Per CLAUDE.md's "Module-level singleton pattern" convention, the module exposes:
- A module-level `_PromptEvolver` class (instantiated once at module level via `_get_evolver()`)
- Module-level **functions** that delegate to the singleton:
  - `select_template(kind, base_prompt, strategy=None) -> tuple[str, str]`
  - `record_outcome(kind, template_id, merged_first_try=False, deployed_verified=False, artifact_commit="") -> None`
  - `stats() -> dict` (for monitoring)
  - `invalidate() -> None` (for testing)

All public functions are thread-safe via `threading.Lock()` at module level.

### Module-Level Constants and Configuration

```python
TEMPLATE_IDS = ["base", "chain_of_thought", "edit_first"]
```
Seeded template variants. These are NOT auto-inserted into the DB; they seed cold-start exploration only (via round-robin when `kind` has no DB rows).

**RESOLVED AMBIGUITY #6:** Cold-start seeding happens in `select_template()`: when no rows exist for a `kind`, it returns the next template from `TEMPLATE_IDS` in round-robin order via `_kind_counters[kind]`. This ensures exploration before historical data exists.

Configuration keys (fleet-pushable via `fleet_control.py`):
- `ORCH_PROMPT_BANDIT_STRATEGY` (default: `"ucb1"`) — arm-selection strategy
- `ORCH_PROMPT_BANDIT_EPSILON` (default: `0.1`) — exploration rate for epsilon-greedy strategy

### `select_template(kind: str, base_prompt: str, strategy: str = None) -> tuple[str, str]`

**Behavior:**
1. Query the `prompt_templates` table for rows where `kind=kind`.
2. If no rows exist: return the next template from `TEMPLATE_IDS` (round-robin) or `(base_prompt, "base")` for the `"base"` arm.
3. If rows exist: aggregate by `template_id` (sum `total_reward` and `n_trials` per template).
4. Call `select_arm(aggregated, strategy=strategy)` to pick the best template using the configured bandit strategy (default: UCB1).
5. Return `(modified_prompt, template_id)`:
   - If `template_id == "base"`: return `(base_prompt, "base")`
   - Otherwise: return `(f"[template:{template_id}]\n{base_prompt}", template_id)`
6. On any DB error: log with `logging.warning()`, return `(base_prompt, "base")`. Never raise.

**RESOLVED AMBIGUITIES #3 & #4:**
- **mean_reward calculation:** `mean_reward = total_reward / n_trials` when `n_trials > 0`
- **N in UCB1 score:** `N = sum of all n_trials for rows where kind=<kind>` (scoped to the specific kind)
- **Untried arms (#7):** Arms with `n_trials == 0` score `+inf`. When multiple arms are untried (all have `+inf` score), ties are broken alphabetically by `template_id` (deterministic first-in-sorted-order strategy, implemented in `candidates.sort(key=lambda x: (-x[0], x[1]))`).

**UCB1 scoring formula:**
```
score = mean_reward + sqrt(2 * ln(N) / n_trials)
```
where `N = sum(all n_trials for this kind)`.

### `record_outcome(kind: str, template_id: str, merged_first_try: bool = False, deployed_verified: bool = False, artifact_commit: str = "") -> None`

**RESOLVED AMBIGUITY #5 (db.insert with resolution='merge-duplicates'):**
- Calls `db.insert("prompt_templates", {...}, resolution="merge-duplicates")`
- This is an **upsert**: if a row with `(kind, template_id)` exists, increment `n_trials` and add `total_reward` to the existing value; otherwise, insert a new row with `n_trials=1`.

**Reward calculation (REWARD HYGIENE, per merged implementation):**
- `reward = 1.0` if `deployed_verified=True`
- `reward = 0.5` if `merged_first_try=True` AND `artifact_commit` is non-empty (evidenced merge)
- `reward = 0.0` otherwise (bare merge claims earn nothing)

**Error handling:** Swallows all exceptions with `logging.warning()`. Never raises or wedges.

### `select_arm(aggregated: dict, strategy: str = None, rng: random.Random = None) -> str`

Helper function that picks the best `template_id` from aggregated arm data using the configured strategy.

**Strategies:**
1. **`ucb1`** (default): UCB1 formula; untried arms score `+inf`
2. **`thompson`**: Sample `Beta(1 + successes, 1 + failures)` per arm, return the highest sample
3. **`epsilon_greedy`**: Explore uniformly with probability `BANDIT_EPSILON`, otherwise exploit the highest acceptance rate

Fallback: unknown strategy logs a warning and falls back to `ucb1`.

**RESOLVED AMBIGUITY #8 (Import):**  
```python
from runner import db
```
This is the correct import; it follows the pattern already used in `runner/prompt_evolver.py`.

### Thread-Safety and Error Handling

**RESOLVED MISSING CRITERION #1 (Thread-Safety):**  
All public module-level functions (`select_template`, `record_outcome`, `stats`) are guarded by `threading.Lock()` at module level. The singleton instance `_evolver` is lazily initialized and never mutated after creation; all mutations happen inside the lock.

**Fail-soft error handling:** All DB operations and exception-prone code paths are wrapped in `try/except`, logging a warning and returning safe defaults:
- `select_template()` returns `(base_prompt, "base")` on error
- `record_outcome()` logs and returns (swallows exception)
- `stats()` returns `{"total_trials": 0, "kinds": {}}` on error

---

## `runner/tests/test_prompt_evolver.py`

**RESOLVED AMBIGUITY #9:** Complete test spec with all 5 unit tests fully specified.

### Test 1: `test_select_template_cold_start`

**Input:**
- Empty `prompt_templates` table (no rows for `kind="refactor"`)
- Call `select_template("refactor", "Fix this code", strategy="ucb1")`

**Expected Output:**
- First call returns `("Fix this code", "base")` (round-robin index 0)
- Second call with same `kind` returns `("[template:chain_of_thought]\nFix this code", "chain_of_thought")` (index 1)
- Third call returns `("[template:edit_first]\nFix this code", "edit_first")` (index 2)
- Fourth call cycles back to `("Fix this code", "base")` (index 0 again)

**Acceptance:** Round-robin counter persists across calls for the same `kind`.

### Test 2: `test_select_template_ucb1_scoring`

**Input:**
- Pre-populate `prompt_templates` with:
  - `(kind="bugfix", template_id="base", total_reward=5.0, n_trials=10)`
  - `(kind="bugfix", template_id="chain_of_thought", total_reward=3.0, n_trials=5)`
  - `(kind="bugfix", template_id="edit_first", total_reward=0.0, n_trials=1)`
- Call `select_template("bugfix", "Fix bug", strategy="ucb1")`

**Expected Output:**  
Verifies that:
- `mean_reward_base = 5.0 / 10 = 0.5`
- `mean_reward_cot = 3.0 / 5 = 0.6`
- `mean_reward_edit = 0.0 / 1 = 0.0`
- N (total trials) = 10 + 5 + 1 = 16
- UCB1 scores computed correctly; returned template_id is the highest-scoring arm (not "base" if another arm's UCB1 > 0.5)
- Returned prompt has `[template:...]` prefix for non-base arms

**Acceptance:** UCB1 formula applied correctly; non-base arm selected if it has higher score.

### Test 3: `test_select_template_untried_arm_beats_tried`

**Input:**
- Pre-populate:
  - `(kind="refactor", template_id="base", total_reward=100.0, n_trials=100)` (acceptance=1.0)
  - `(kind="refactor", template_id="chain_of_thought", total_reward=0.0, n_trials=0)` (untried)
- Call `select_template("refactor", "Refactor", strategy="ucb1")`

**Expected Output:**
- Returned `template_id == "chain_of_thought"` (untried arm with `+inf` score beats any tried arm)
- Returned prompt is `"[template:chain_of_thought]\nRefactor"`

**Acceptance:** Untried arms (`n_trials == 0`) always score `+inf` and outrank tried arms.

### Test 4: `test_record_outcome_reward_hygiene`

**Input & Calls:**
1. `record_outcome("bugfix", "base", merged_first_try=True, deployed_verified=False, artifact_commit="")` → reward should be 0.0 (bare merge)
2. `record_outcome("bugfix", "base", merged_first_try=True, deployed_verified=False, artifact_commit="abc123")` → reward should be 0.5 (merge + artifact)
3. `record_outcome("bugfix", "base", merged_first_try=False, deployed_verified=True, artifact_commit="")` → reward should be 1.0 (deployed+verified)
4. Verify rows inserted/upserted correctly in DB

**Expected Outcome:**
- Row for `(kind="bugfix", template_id="base")` exists after all calls
- If initial row did not exist: 3 rows inserted (one per call)
- If initial row exists: final row has `n_trials=3, total_reward=1.5` (0.0 + 0.5 + 1.0, upserted)

**Acceptance:** Reward hygiene applied correctly; `resolution="merge-duplicates"` upserts as expected.

### Test 5: `test_record_outcome_exception_handling`

**Input:**
- Mock `db.insert()` to raise an exception (e.g., `RuntimeError("DB connection failed")`)
- Call `record_outcome("bugfix", "base", merged_first_try=True)`

**Expected Output:**
- No exception raised by `record_outcome()` (swallowed)
- `logging.warning()` was called with a message containing "Failed to record outcome" and the exception
- Function returns normally

**Acceptance:** Exceptions are logged and swallowed; function never wedges the caller.

---

## Database Schema Assumptions

**Table:** `prompt_templates`  
**Columns:** `kind` (text), `template_id` (text), `total_reward` (float), `n_trials` (int)  
**Key:** Implied primary key or unique constraint on `(kind, template_id)` for upsert semantics.

The module does NOT create or migrate the schema; assume it exists.

---

## Acceptance Criteria

1. **Module-level singleton pattern followed**: Public functions delegate to a thread-safe singleton instance; no direct class instantiation by callers.
2. **Thread-safety guaranteed**: All public functions guarded by `threading.Lock()`; safe for concurrent calls.
3. **Fail-soft error handling**: All exceptions caught and logged; safe defaults returned; no exceptions raised to caller.
4. **UCB1 scoring correct**: Formula applied correctly; untried arms always score `+inf`; ties broken alphabetically.
5. **Reward hygiene enforced**: Deployed + verified = 1.0; merge + artifact = 0.5; bare merge = 0.0.
6. **Upsert semantics**: `db.insert(..., resolution="merge-duplicates")` correctly upserts (increments n_trials and total_reward for existing rows).
7. **Cold-start exploration**: Round-robin over `TEMPLATE_IDS` when no rows exist for a `kind`.
8. **Configuration keys fleet-pushable**: `ORCH_PROMPT_BANDIT_STRATEGY` and `ORCH_PROMPT_BANDIT_EPSILON` read from environment at module load time.
9. **No breaking changes**: No modifications to `runner.py`, migrations, or other files; existing callers unaffected.
10. **Tests comprehensive**: All 5 unit tests pass; 20+ assertions covering cold-start, UCB1 scoring, untried arms, reward hygiene, and exception handling.

---

## Implementation Notes

- **Existing code** at `runner/prompt_evolver.py` already implements the full spec (including Thompson sampling and epsilon-greedy variants not in the original spec but aligned with the singleton/fail-soft patterns).
- **Test file** at `runner/tests/test_prompt_evolver.py` should be created or extended to include all 5 test cases above if not already present.
- **No schema migration needed** — assume `prompt_templates` table exists in the deployment environment.
