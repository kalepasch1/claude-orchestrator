# Refined Spec: `runner/prompt_evolver.py` — UCB1 Bandit Template Selection

**Status:** Refinement of patch template f4b5aaf6893c  
**Date:** 2026-08-05

---

## Intent (Resolved)

Implement a module that tracks prompt template effectiveness across experiment trials using the UCB1 multi-armed bandit algorithm. When asked to select a template for a given category (`kind`), choose based on empirical reward (merge-on-first-try rate) and exploration bonus. Record trial outcomes to update template statistics for future selection.

**Use case:** Operators can evolve prompt quality over many automated runs by comparing performance across template variants (chain-of-thought, edit-first, etc.) without manual tuning.

---

## Implementation Scope

**Files to create (exactly):**
- `runner/prompt_evolver.py` — Main module with module-level API
- `runner/tests/test_prompt_evolver.py` — 5+ test cases per acceptance criteria

**Files to modify (none):**  
- Do NOT touch `runner.py`, `.claude/settings.local.json`, migrations, or other modules.

---

## Database Schema (Required Upfront)

**Table:** `prompt_templates`  
**Columns:**
| Column | Type | Semantics |
|--------|------|-----------|
| `kind` | TEXT | Categorical identifier (e.g., "refactor", "security_review", "summary"). Caller-provided; no fixed enum. |
| `template_id` | TEXT | Unique identifier for a template variant (e.g., "base", "chain_of_thought", "edit_first"). |
| `total_reward` | FLOAT | Cumulative reward across all trials: sum of 1.0 (merged first try) or 0.0 (did not). Updated on upsert. |
| `n_trials` | INTEGER | Count of trials for this (kind, template_id) pair. Incremented on upsert. |
| **Primary Key** | (kind, template_id) | Composite key ensures one row per template variant per kind. |

**When to initialize schema:**  
Database schema should exist before the module is imported (i.e., created by a migration before runner startup). The module assumes the table exists and makes no CREATE TABLE calls.

---

## Module API

### `select_template(kind: str, base_prompt: str) -> tuple[str, str]`

**Purpose:** Select the best-performing template for a category using UCB1 scoring.

**Input:**
- `kind` (str): Categorical identifier for grouping templates (e.g., "security_review"). No validation of values; caller is responsible for consistent naming.
- `base_prompt` (str): Fallback prompt text if no templates exist or on error. If None or empty, treat as empty string `""`.

**Output:**
- Tuple of `(modified_prompt, template_id)` where:
  - `modified_prompt`: The prompt text to use. For `template_id="base"`, returns `base_prompt` unmodified. For others, prepends a one-line variant tag: `f"[template:{template_id}]\n{base_prompt}"`.
  - `template_id`: The ID of the selected template (str). Can be `"base"` or any seeded ID like `"chain_of_thought"`, `"edit_first"`, etc.

**Algorithm:**
1. Query `prompt_templates` table for all rows where `kind=kind`.
2. If no rows exist (cold-start):
   - Return `(base_prompt, "base")` immediately.
   - The caller may later seed templates via `record_outcome()`.
3. If rows exist, compute UCB1 score for each:
   - For untried arms (`n_trials == 0`): score = `+∞` (infinity). Always prefer over tried arms.
   - For tried arms: `score = (total_reward / n_trials) + sqrt(2 * ln(N) / n_trials)`, where `N = sum of all n_trials for this kind`.
   - Select the template with the **highest** score.
4. Return the selected template's ID and modified prompt.

**Error handling (fail-soft):**
- On any DB error (connection, query, etc.), log via `logging.warning(...)` and return `(base_prompt, "base")`. Never raise.
- If `base_prompt` is None, treat as `""`.

---

### `record_outcome(kind: str, template_id: str, merged_first_try: bool) -> None`

**Purpose:** Record the result of a trial using a selected template.

**Input:**
- `kind` (str): Same category used in `select_template()`. No validation.
- `template_id` (str): The ID of the template that was used (e.g., "base", "chain_of_thought").
- `merged_first_try` (bool): True if the outcome was a success (e.g., the diff merged without rework); False otherwise.

**Behavior:**
1. Compute reward: `reward = 1.0 if merged_first_try else 0.0`.
2. Insert/upsert into `prompt_templates`:
   ```python
   db.insert(
       "prompt_templates",
       {"kind": kind, "template_id": template_id, "total_reward": reward, "n_trials": 1},
       resolution="merge-duplicates"
   )
   ```
   **Important:** Use the `resolution="merge-duplicates"` keyword argument (not `upsert=True`). This tells the database to upsert: if a row with the same (kind, template_id) exists, **increment** `n_trials` by 1 and **add** `reward` to `total_reward`; otherwise, insert a new row.

3. Error handling (fail-soft):
   - Swallow all exceptions (DB errors, invalid inputs, etc.) with a `logging.warning(f"Failed to record outcome for kind={kind}, template_id={template_id}: ...")` call.
   - Never raise; always return None.

---

## Module Seeding & Constants

**Define module-level constant:**
```python
TEMPLATE_IDS = ["base", "chain_of_thought", "edit_first"]
```

**Cold-start behavior:**  
On the first call to `select_template()` for a new `kind`, the database has no rows and the function returns `(base_prompt, "base")`. Callers may then invoke `record_outcome()` with any of the seeded IDs or custom IDs to begin accumulating trials. The module does NOT auto-insert these IDs; seeding is caller-driven (or via migrations if pre-population is desired).

---

## Import & Module Structure

**Location:** `runner/prompt_evolver.py`

**Import pattern (resolved):**  
Since the module is inside the `runner/` package, use absolute imports from the runner package:
```python
from runner import db
import logging
```

Or, if runner is not yet a package, use:
```python
import sys
sys.path.insert(0, os.path.dirname(__file__))
# Then import db from parent or sibling module
```

**Recommended:** Ensure `runner/` is a Python package (has `__init__.py`), then use `from runner import db`.

---

## Thread Safety & Concurrency

**Requirement:** The module must be thread-safe if called from multiple runner threads.

**Implementation:** Protect database access with a `threading.Lock()`. Minimize the critical section:
- Acquire lock only during DB query/insert, not for computation.
- Release lock before returning.
- Example:
  ```python
  import threading
  _lock = threading.Lock()
  
  def select_template(kind, base_prompt):
      with _lock:
          # DB query here
      # Computation here (UCB1 scoring) outside lock
      return (modified_prompt, template_id)
  ```

---

## Acceptance Criteria

**All of the following must pass to merge:**

### 1. Test Coverage (5+ test cases, all passing)

| # | Test Name | Scenario | Assert |
|---|-----------|----------|--------|
| 1 | `test_select_template_empty_db` | `select_template()` called on empty DB for a kind | Returns `(base_prompt, "base")` unmodified |
| 2 | `test_select_template_untried_arm_preferred` | Multiple templates exist; one has `n_trials=0` | Selects the untried arm (score = infinity) |
| 3 | `test_select_template_ucb1_scoring` | Multiple tried arms exist; verify selection matches highest UCB1 score | Correct template selected based on formula |
| 4 | `test_record_outcome_insert` | `record_outcome()` called for a new (kind, template_id) pair | Row inserted: `n_trials=1`, `total_reward=1.0` or `0.0` |
| 5 | `test_record_outcome_upsert` | `record_outcome()` called twice for same (kind, template_id) with different outcomes | Stats accumulated: `n_trials=2`, `total_reward=1.0` (if one success, one fail) |
| **Bonus** | `test_record_outcome_error_graceful` | `record_outcome()` called with invalid/missing DB connection | No exception raised; warning logged |
| **Bonus** | `test_select_template_variant_tag_prepended` | `select_template()` returns non-base template | Prompt includes `f"[template:{template_id}]\n"` prefix |

**Coverage requirement:** All main code paths covered (empty DB, cold-start, UCB1 selection, upsert, error cases). Use `pytest --cov=runner.prompt_evolver` to verify ≥90% line coverage.

### 2. Build & Tests Pass

- `pytest runner/tests/test_prompt_evolver.py -v` — all 5+ tests pass.
- No new linting or typecheck errors: `ruff check runner/prompt_evolver.py`, `mypy runner/prompt_evolver.py` (if enabled).

### 3. No Other Files Modified

- Diff touches only `runner/prompt_evolver.py` and `runner/tests/test_prompt_evolver.py`.
- Verify with `git diff --name-only`: exactly 2 files.

### 4. Fail-Soft Behavior Verified

- Any DB error is caught and logged (not raised).
- Function returns sensible defaults (base prompt, base template ID).
- Test calls `record_outcome()` with mocked DB.insert() that raises; verifies logging and no exception propagated.

### 5. Database Schema Exists

- Schema migration or initialization doc is provided so ops know how to create `prompt_templates` table.
- Module assumes table exists; if called before migration, DB error is logged and handled gracefully (see fail-soft).

### 6. Performance & Memory

- `select_template()` DB query completes in <10ms (typical indexed lookup on small table).
- No memory leaks in the lock or db connection handling.
- Module-level lock does not cause contention bottleneck (tests with concurrent calls pass).

### 7. Documentation & Comments

- Module docstring explains intent, algorithm, and usage.
- `select_template()` and `record_outcome()` have docstrings.
- No excessive inline comments; only explain non-obvious invariants (e.g., "untried arms score infinity").

---

## Resolved Ambiguities

| Ambiguity | Resolution | Rationale |
|-----------|-----------|-----------|
| Intent corrupted | "Bandit-based prompt template selection for multi-armed exploration of variant effectiveness" | Clear, actionable intent tied to use case |
| Test spec incomplete | Defined 5 concrete test scenarios with exact assertions | Ensures all paths tested and acceptance is verifiable |
| `kind` parameter undefined | Categorical string (e.g., "security_review"); caller-provided, no enum | Flexible for future template categories without code changes |
| TEMPLATE_IDS seeding | Define module constant `TEMPLATE_IDS`; no auto-insert on cold-start | Caller-driven seeding allows gradual rollout; avoids hidden DB state |
| `resolution="merge-duplicates"` behavior | On upsert: increment `n_trials`, add `reward` to `total_reward` | Enables UCB1 mean_reward calculation and trial accumulation |
| `total_reward` accumulation | Accumulates across trials; `mean_reward = total_reward / n_trials` | Required for UCB1 scoring formula |
| Import guidance | Use `from runner import db` after ensuring `runner/` is a package | Consistent with Python package structure; fallback to sys.path if needed |
| Thread safety | Protect DB queries/inserts with `threading.Lock()`; compute UCB1 outside lock | Follows project conventions (module-level singleton with explicit lock) |
| `base_prompt` None/empty | Treat None as empty string `""`; return as-is if no templates or on error | Graceful degradation; never crashes on bad input |
| Patch template reference | Metadata only; not relevant to implementation | Removed from refined spec |

---

## Deployment Notes

**Initialization checklist:**
- [ ] Database migration creates `prompt_templates` table with schema above (before runner startup).
- [ ] `runner/prompt_evolver.py` added to repo.
- [ ] `runner/__init__.py` exists and exports `db` module (or adjust imports).
- [ ] Tests pass and coverage ≥90%.
- [ ] Docs/examples show how to call `select_template()` and `record_outcome()` from orchestrator workflows.

**Optional future work (not in scope):**
- Auto-seeding initial templates on first call for a kind (currently caller-driven).
- Persistence of template IDs across runner restarts (currently relies on DB).
- Template retirement policy (e.g., remove arms with <N trials).
