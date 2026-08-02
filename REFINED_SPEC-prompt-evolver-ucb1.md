# REFINED SPEC: Add PromptEvolver UCB1 Bandit (f4b5aaf6893c)

## Intent
Implement a multi-armed bandit (UCB1) system to select and optimize prompt templates per message kind. Each kind (e.g., "summarize", "refactor") maintains empirical reward signals (first-try merge rate) for multiple template variants. The module provides two entry points: **select_template** to choose which variant to try next (balancing exploration vs. exploitation), and **record_outcome** to log the result back to the database.

---

## Scope
Create exactly two files: `runner/prompt_evolver.py` and `runner/tests/test_prompt_evolver.py`. 
**Modify no other files.** Do not touch `runner.py`, `.claude/settings.local.json`, or migration files.

---

## Implementation

### `runner/prompt_evolver.py`

Provide **module-level functions** (not a class API) that delegate to a thread-safe singleton instance, following project conventions.

#### Constants
```python
TEMPLATE_IDS = ["base", "chain_of_thought", "edit_first"]
```
These are the default variant IDs. When `select_template` is called and the database is empty for a kind, the module may suggest trying one of these IDs. They are **not** auto-inserted into the database.

#### Module-level function: `select_template(kind: str, base_prompt: str) -> tuple[str, str]`

**Behavior:**
1. Query `prompt_templates` table for rows where `kind=kind`. Table schema: `{kind, template_id, total_reward, n_trials}`.
2. **If no rows exist** for this kind: return `(base_prompt, "base")` — base is always the fallback.
3. **For each row**, compute a UCB1 score:
   - If `n_trials == 0` (untried arm): score = infinity — always prefer untried arms.
   - Otherwise: `mean_reward + sqrt(2 * ln(N) / n_i)` where:
     - `mean_reward = total_reward / n_trials`
     - `N = sum of all n_trials for this kind` (sum across all template variants for this specific kind)
     - `n_i = n_trials` for this specific arm
4. **Select the arm with the highest UCB1 score.** In case of tie, order by `template_id` (alphabetically).
5. **Format the returned prompt:**
   - If `template_id == "base"`: return `(base_prompt, "base")` unmodified.
   - Otherwise: prepend a one-line tag: `(f"[template:{template_id}]\n{base_prompt}", template_id)`.
6. **Error handling:** On any database error (connection, query, schema), log it with `logging.warning(...)` and return `(base_prompt, "base")`. Never raise.

**Return type:** `tuple[str, str]` — `(modified_prompt, template_id)`

---

#### Module-level function: `record_outcome(kind: str, template_id: str, merged_first_try: bool) -> None`

**Behavior:**
1. Compute `reward = 1.0 if merged_first_try else 0.0`.
2. Call `db.insert("prompt_templates", {"kind": kind, "template_id": template_id, "total_reward": reward, "n_trials": 1}, resolution="merge-duplicates")`.
   - **Note:** Use the `resolution="merge-duplicates"` **keyword argument** (not `upsert=True`).
   - If the row already exists (same kind + template_id), the insert merges (adds to totals and n_trials).
3. **Error handling:** Swallow all exceptions (database connection errors, permission errors, etc.) with `logging.warning(f"Failed to record outcome: {e}")`. Never raise. This follows the project's fail-soft pattern.

**Return type:** `None`

---

### `runner/tests/test_prompt_evolver.py`

Implement exactly these test cases (plus edge cases as appropriate):

1. **test_select_template_empty_db**: When no rows exist for a kind, returns `(base_prompt, "base")`.

2. **test_select_template_one_tried_arm**: Database has one arm with `n_trials=5, total_reward=3.5`. Verify:
   - The function returns that arm's `template_id` and the modified prompt (with tag prepended).
   - No crash; correct UCB1 score computation (mean_reward = 0.7).

3. **test_select_template_untried_vs_tried**: Database has one tried arm (`n_trials=5, total_reward=5.0`) and one untried arm (`n_trials=0`). Verify:
   - The untried arm is selected (infinite score).
   - The returned prompt includes the `[template:...]` tag.

4. **test_select_template_base_variant**: When `template_id="base"` is returned, verify the prompt is **not** modified (no tag prepended).

5. **test_record_outcome_success**: Call `record_outcome(kind="foo", template_id="bar", merged_first_try=True)`. Verify:
   - `db.insert()` is called with correct arguments: table name, dict with `{"kind": "foo", "template_id": "bar", "total_reward": 1.0, "n_trials": 1}`, and `resolution="merge-duplicates"`.
   - Function does not raise.

6. **test_record_outcome_failure**: Call `record_outcome(...)` when `db.insert()` raises an exception. Verify:
   - A warning is logged.
   - No exception propagates.
   - The function returns normally.

7. **test_ucb1_calculation_accuracy**: Set up multiple arms with known reward/trial counts. Compute expected UCB1 scores by hand. Verify the selected arm matches the mathematically highest score.

---

## Acceptance Criteria

- [ ] `runner/prompt_evolver.py` exists with module-level functions (not a class API).
- [ ] `select_template()` queries `prompt_templates` table, applies UCB1, and returns `(prompt, template_id)`.
- [ ] `select_template()` returns base prompt unmodified when `template_id="base"`, and prepends `[template:...]` tag for other IDs.
- [ ] `select_template()` catches and logs database errors; returns `(base_prompt, "base")` on failure.
- [ ] `record_outcome()` calls `db.insert(..., resolution="merge-duplicates")` with correct reward value (1.0 for success, 0.0 for failure).
- [ ] `record_outcome()` swallows all exceptions and logs warnings.
- [ ] UCB1 formula is correct: `mean_reward + sqrt(2 * ln(N) / n_i)` where N = sum of all n_trials for this kind.
- [ ] All 7+ test cases pass; tests mock `db.insert()` to verify calls without hitting a real database.
- [ ] No other files are modified.
- [ ] Build/tests pass cleanly.

---

## Technical Notes

**On DB import:**
The spec assumes `from runner import db` is already available (db module is part of runner's public API or runner.__init__.py exports it). If not, verify the import path or check whether `db.insert(...)` exists with a `resolution=` kwarg.

**On UCB1 and N:**
N is the **sum of n_trials across all rows with the same kind**. This is the total number of trials ever made for this kind (across all template variants combined). It increases each time any variant is tried for this kind.

**On cold-start / TEMPLATE_IDS:**
The constant `TEMPLATE_IDS` lists default variants. It is not used to auto-populate the database. It may be used by a caller (not this module) to seed suggestions when the database is empty.

**On singleton vs. class:**
Per project conventions (fail-soft, module-level functions), the module provides `select_template()` and `record_outcome()` as importable functions, not a `PromptEvolver()` class. Internally, they may delegate to a singleton instance if state needs to be shared, but the API surface is functional.

---

## Files Changed

| File | Status | Notes |
|------|--------|-------|
| `runner/prompt_evolver.py` | **Create** | Module with select_template() and record_outcome() |
| `runner/tests/test_prompt_evolver.py` | **Create** | 7+ test cases, all mock db.insert() |
| (all others) | Unchanged | No modifications to runner.py, settings, migrations, etc. |
