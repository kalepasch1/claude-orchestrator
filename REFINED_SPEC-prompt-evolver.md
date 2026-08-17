# Refined Spec: Prompt Template Optimizer with UCB1 Bandit

**Date:** 2026-08-16  
**Status:** READY_FOR_IMPLEMENTATION  
**Purpose:** Implement a bandit-based prompt template selector (`runner/prompt_evolver.py`) with persistent reward tracking, following fail-soft error handling and module-level singleton conventions.

---

## Intent (Resolved)

Implement an **explore-exploit optimizer** that selects prompt templates using the UCB1 (Upper Confidence Bound) algorithm, tracking which variants produce merged-on-first-try outcomes. The module learns per-kind (e.g., per task type) which template variants work best and recommends them probabilistically—favoring untried arms, then balancing mean reward against uncertainty.

---

## Files to Create/Modify

**Create only:**
- `runner/prompt_evolver.py` — Core module with singleton and public API
- `runner/tests/test_prompt_evolver.py` — Comprehensive test suite (5 tests)

**Modify no other files** (runner.py, settings, migrations, etc. remain untouched).

---

## Database Schema (Resolved)

### `prompt_templates` Table

**Assumption:** Table exists (created by schema migration before module first use). Module does not create it.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `kind` | TEXT | NOT NULL, part of PK | Task type/category (e.g., "backlog-batch", "qafix") |
| `template_id` | TEXT | NOT NULL, part of PK | Template identifier (e.g., "base", "chain_of_thought", "edit_first") |
| `total_reward` | FLOAT | NOT NULL, default 0.0 | Sum of all outcomes (0 or 1 per trial) |
| `n_trials` | INTEGER | NOT NULL, default 0 | Count of trials for this (kind, template_id) pair |
| **PRIMARY KEY** | (kind, template_id) | — | Ensures one row per variant per kind |

**Merge-duplicates behavior (Resolved):** When `db.insert(..., resolution="merge-duplicates")` is called with an existing (kind, template_id):
- `new_total_reward = existing_total_reward + incoming_total_reward`
- `new_n_trials = existing_n_trials + incoming_n_trials`
- This accumulates outcomes across multiple calls.

---

## Module API

### Singleton Pattern (Resolved)

The module provides **module-level functions** (not a class users instantiate) that delegate to a thread-safe singleton. Users call functions directly; they do not instantiate `PromptEvolver`.

```python
# Module-level API (users call these)
def select_template(kind: str, base_prompt: str) -> tuple[str, str]: ...
def record_outcome(kind: str, template_id: str, merged_first_try: bool) -> None: ...

# Internal: singleton class
class _PromptEvolver: ...
_evolver = _PromptEvolver()  # Module-level singleton instance
```

---

## `select_template(kind: str, base_prompt: str) -> tuple[str, str]`

**Purpose:** Query the database, compute UCB1 scores, and return the best-scoring template variant.

**Behavior:**

1. Query `prompt_templates` for all rows where `kind = kind`.
2. If no rows found:
   - Return `(base_prompt, "base")` unmodified.
   - Do NOT seed the database; cold-start is lazy (first call to `record_outcome` seeds it).
3. **Scoring:**
   - Compute N = sum of all `n_trials` for this kind (across all template_id).
   - For each row:
     - If `n_trials == 0` (untried arm): score = `∞` (always preferred).
     - If `n_trials > 0` (tried arm): score = `mean_reward + sqrt(2 * ln(N) / n_trials)`
       - where `mean_reward = total_reward / n_trials`.
   - Select the row with the highest score (ties broken by earliest row insertion).
4. **Template variant tag:**
   - If `template_id == "base"`: return `(base_prompt, "base")` unmodified.
   - Otherwise: prepend a single-line tag: `f"[template:{template_id}]\n{base_prompt}"`.
5. **Return:** `(modified_prompt, template_id)`.

**Error handling (Resolved):**
- On any DB error (connection, query): log warning, return `(base_prompt, "base")`.
- **Never raise an exception.**

**Example:**
```python
# Given kind="backlog-batch", base_prompt="Describe this issue"
# DB has: (kind="backlog-batch", template_id="chain_of_thought", total_reward=3.0, n_trials=3)
#         (kind="backlog-batch", template_id="base", total_reward=2.0, n_trials=2)
# Returns: ("[template:chain_of_thought]\nDescribe this issue", "chain_of_thought")
```

---

## `record_outcome(kind: str, template_id: str, merged_first_try: bool) -> None`

**Purpose:** Record the result of using a template and update its reward statistics.

**Behavior:**

1. Compute `reward = 1.0 if merged_first_try else 0.0`.
2. Call:
   ```python
   db.insert(
       "prompt_templates",
       {"kind": kind, "template_id": template_id, "total_reward": reward, "n_trials": 1},
       resolution="merge-duplicates"
   )
   ```
   - **Use keyword argument `resolution="merge-duplicates"`** (not `upsert=True`).
   - The DB layer will merge (sum) if (kind, template_id) already exists.
3. **Error handling:** Catch all exceptions, log as `logging.warning(...)`, never raise.

**Example:**
```python
# First call: inserts {kind="qafix", template_id="edit_first", total_reward=1.0, n_trials=1}
record_outcome("qafix", "edit_first", merged_first_try=True)

# Second call (same kind, same template): DB merges to {total_reward=2.0, n_trials=2}
record_outcome("qafix", "edit_first", merged_first_try=True)

# Third call: DB merges to {total_reward=2.0, n_trials=3} (0.0 added this time)
record_outcome("qafix", "edit_first", merged_first_try=False)
```

---

## Template Variants (Resolved)

The module defines:
```python
TEMPLATE_IDS = ["base", "chain_of_thought", "edit_first"]
```

**Modifications applied by `select_template` when returning a variant:**

| Template ID | Tag | Prompt modification |
|---|---|---|
| `"base"` | (none) | Return `base_prompt` unmodified |
| `"chain_of_thought"` | `[template:chain_of_thought]` | Prepend tag; adds "Think step-by-step:" guidance to base_prompt via tag context |
| `"edit_first"` | `[template:edit_first]` | Prepend tag; signals "Refactor before merge" intent via tag context |

**Implementation note:** The tag itself provides the semantic hint; the caller's prompt handling system interprets `[template:X]` tags. Do not modify the base_prompt text itself.

---

## Acceptance Criteria (Resolved)

### Functional

- [ ] `select_template()` returns `(base_prompt, "base")` when DB table is empty.
- [ ] `select_template()` applies UCB1 scoring correctly (untried arms score ∞, tried arms use upper confidence bound formula).
- [ ] Returned modified prompt includes `[template:ID]` tag for non-base templates.
- [ ] `record_outcome()` inserts with `n_trials=1` and reward ∈ {0.0, 1.0}.
- [ ] Successive calls to `record_outcome()` with same (kind, template_id) accumulate via merge-duplicates (n_trials increments, total_reward sums).
- [ ] Both functions handle DB errors gracefully: log warning, return sensible default, never raise.

### Thread Safety

- [ ] Module functions are thread-safe (protected by lock if accessing singleton state).
- [ ] Concurrent calls to `select_template()` and `record_outcome()` do not corrupt state.

### Code Quality

- [ ] Follows project conventions: fail-soft error handling, module-level singleton pattern.
- [ ] All magic numbers (e.g., `2` in UCB1 formula `sqrt(2 * ln(N) / n_trials)`) are named constants.
- [ ] Docstrings explain *why* fail-soft paths exist, not just what they do.
- [ ] No hardcoded secrets or credentials.

### Testing (5 Required Tests)

- [ ] **Test 1: cold-start (empty DB)** — Verify `select_template()` returns `(base_prompt, "base")` when no rows exist.
- [ ] **Test 2: UCB1 scoring** — Create rows with varying n_trials and total_reward; verify highest UCB1 score is selected.
- [ ] **Test 3: untried arms (infinity score)** — Add a row with n_trials=0; verify it is always selected over tried arms.
- [ ] **Test 4: merge-duplicates accumulation** — Call `record_outcome()` twice with same (kind, template_id); verify n_trials increments and total_reward sums.
- [ ] **Test 5: error handling** — Simulate DB error (mock connection failure); verify graceful fallback and logging, no exception raised.

---

## Implementation Checklist

- [ ] Create `runner/prompt_evolver.py` with module-level singleton and functions.
- [ ] Create `runner/tests/test_prompt_evolver.py` with 5 tests covering functional, thread safety, and error paths.
- [ ] Use `logging.warning()` for all fail-soft error logs.
- [ ] Import `math.log`, `math.sqrt` for UCB1 formula.
- [ ] Define `TEMPLATE_IDS` as a module constant.
- [ ] Ensure DB table schema exists (assume it, do not create).
- [ ] Run `pytest runner/tests/test_prompt_evolver.py -v` and verify all 5 tests pass.
- [ ] Verify no other files are modified.

---

## Resolutions Summary

| Ambiguity | Resolution | Rationale |
|-----------|-----------|-----------|
| Corrupted intent | "Explore-exploit optimizer for prompt templates using UCB1" | Clear, actionable, aligns with bandit algorithm |
| PATCH TEMPLATE ref | New feature, not a patch; create from scratch | Simplified scope, no existing code to preserve |
| DB schema | Define table with exact column names/types; assume it exists | Explicit types prevent type errors; schema migration owns creation |
| merge-duplicates behavior | Sum totals when (kind, template_id) exists | Standard upsert pattern for cumulative stats |
| Reward accumulation | `n_trials=1` per insert; merge-duplicates sums across calls | Matches DB insert API; singleton tracks per-call logic |
| Missing tests | Define all 5: cold-start, UCB1, infinity, merge, error | Complete coverage of core paths |
| Singleton pattern | Module-level functions delegate to _PromptEvolver instance | Follows project convention; users call functions, not class |

**Confidence: 0.92** (Clear resolution of all major ambiguities; minor implementation details remain for developer judgment per project style.)
