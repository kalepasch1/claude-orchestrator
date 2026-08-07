# Refined Spec: `runner/prompt_evolver.py` — UCB1 Bandit Template Selector

## Intent (Resolved)
Implement a UCB1-armed-bandit algorithm to select prompt templates per `kind`, optimizing for merge-on-first-try success. The module learns which templates work best for each prompt kind and surfaces the highest-confidence choice.

---

## File Scope
- **Create**: `runner/prompt_evolver.py`, `runner/tests/test_prompt_evolver.py`
- **Modify**: None. No changes to `runner.py`, settings, migrations, or other modules.
- **DB table contract**: `prompt_templates` with columns `kind`, `template_id`, `total_reward`, `n_trials`

---

## `runner/prompt_evolver.py` — Implementation

### Module-level API

```python
TEMPLATE_IDS = ["base", "chain_of_thought", "edit_first"]

def select_template(kind: str, base_prompt: str) -> tuple[str, str]:
    """Select best template for a prompt kind using UCB1 bandit logic.
    
    Returns: (modified_prompt, template_id)
    """

def record_outcome(kind: str, template_id: str, merged_first_try: bool) -> None:
    """Record trial outcome; updates prompt_templates DB."""
```

### `select_template(kind: str, base_prompt: str) -> tuple[str, str]`

**DB Query Behavior:**
- Query `prompt_templates` where `kind = kind`.
- If no rows exist (cold-start): **Return the first untried template in `TEMPLATE_IDS` order** (i.e., `("base", "base")` initially, then `("chain_of_thought", "chain_of_thought")` if "base" is tried).
  - *Rationale (Resolved cold-start ambiguity):* Deterministic round-robin discovery avoids randomness and makes testing reproducible.

**UCB1 Scoring (for tried arms with n_trials > 0):**
- `N = sum of all n_trials for this kind across all template_ids`.
- For each row: `mean_reward = total_reward / n_trials`.
- UCB1 score: `mean_reward + sqrt(2 * ln(N) / n_trials)`.
- **Untried arms (`n_trials == 0`):** Score = +infinity (always preferred over tried arms).
- **Tiebreaker for multiple untried arms:** Use position in `TEMPLATE_IDS` (first position wins).
  - *Rationale (Resolved tiebreaker ambiguity):* Deterministic ordering ensures reproducible behavior.

**Return Values:**
- If `template_id == "base"`: Return `(base_prompt, "base")` unmodified.
- Otherwise: Return `(f"[template:{template_id}]\n{base_prompt}", template_id)`.
  - **Variant tag idempotence (Resolved):** Before prepending, check if `base_prompt` already contains `[template:...]`. 
    - If it contains the same tag (e.g., already `[template:chain_of_thought]`): skip prepend, return as-is.
    - If it contains a *different* tag: log warning `"PromptEvolver: Replacing existing tag X with Y"`, strip old tag, prepend new one.
    - If no tag exists: prepend normally.

**Error Handling (Fail-soft per conventions):**
- On any DB error (connection, query, parse): Log `logging.warning(f"PromptEvolver.select_template({kind}): {error}")`, return `(base_prompt, "base")`.
- Never raise. Always return a valid tuple.

---

### `record_outcome(kind: str, template_id: str, merged_first_try: bool) -> None`

**Reward Calculation:**
- `reward = 1.0 if merged_first_try else 0.0`.

**DB Insert with merge-duplicates (Resolved merge-duplicates ambiguity):**
```python
db.insert(
    "prompt_templates",
    {"kind": kind, "template_id": template_id, "total_reward": reward, "n_trials": 1},
    resolution="merge-duplicates"
)
```

- **What "merge-duplicates" means:** If `(kind, template_id)` already exists, **sum** `total_reward` and **increment** `n_trials` by 1 (accumulate trial history).
  - Pseudo-SQL: `UPDATE ... SET total_reward = total_reward + reward, n_trials = n_trials + 1 WHERE kind=? AND template_id=?; INSERT IF NOT FOUND`.
- This is different from `upsert=True` (which would replace); "merge-duplicates" **accumulates**.

**DB Import (Resolved import ambiguity):**
- Use `from runner import db` — accesses module-level singleton per [[fail-soft-singletons]].
- Do NOT use `import db` directly.

**Error Handling (Fail-soft per conventions):**
- Swallow all exceptions with `logging.warning(f"PromptEvolver.record_outcome({kind}, {template_id}): {error}")`.
- Never raise. The method returns `None` in all cases.

**Invalid template_id behavior (Resolved ambiguity):**
- If `template_id` is not in `TEMPLATE_IDS` and not "base": Still record it (allows experimenting with new templates dynamically). Log `logging.debug(...)` if desired, but do not reject.

---

## `runner/tests/test_prompt_evolver.py` — Acceptance Tests

### Test 1: `test_select_template_cold_start`
- **Setup:** Empty `prompt_templates` table.
- **Assertion:** First call to `select_template(kind="my_kind", base_prompt="...")` returns `("...", "base")`.
- **Then:** Simulate recording outcome for "base", call again. Next call returns template with `template_id="chain_of_thought"`.

### Test 2: `test_record_outcome_accumulates_on_duplicate`
- **Setup:** Record outcome for `(kind="foo", template_id="bar", merged_first_try=True)`.
- **Query result:** `total_reward=1.0, n_trials=1`.
- **Then:** Record outcome again with `merged_first_try=False`.
- **Query result:** `total_reward=1.0, n_trials=2` (merged-duplicates accumulated, not replaced).

### Test 3: `test_ucb_prefers_untried_arm`
- **Setup:** Mock DB query to return two arms: one tried `(template_id="a", n_trials=5, total_reward=2.5)`, one untried `(template_id="b", n_trials=0, total_reward=0)`.
- **Assertion:** `select_template(kind="x", ...)` returns `template_id="b"` (untried arm preferred despite tried arm having positive reward).

### Test 4: `test_ucb_tiebreaker_among_untried`
- **Setup:** Mock DB query to return three untried arms: `template_id="chain_of_thought"`, `template_id="edit_first"`, `template_id="base"` (all with `n_trials=0`).
- **Assertion:** `select_template` returns template at position 0 in the result set (or position in `TEMPLATE_IDS` if ordering is controllable). Verify deterministic tiebreaker.

### Test 5: `test_variant_tag_idempotence`
- **Setup:** Call `select_template(kind="x", base_prompt="[template:chain_of_thought]\nOriginal prompt", ...)` when `chain_of_thought` template is selected.
- **Assertion:** No double tag prepended; returns `("[template:chain_of_thought]\nOriginal prompt", "chain_of_thought")`.
- **Then:** Call with a *different* selected template (e.g., "edit_first").
- **Assertion:** Old tag stripped, new tag prepended; returns `("[template:edit_first]\nOriginal prompt", "edit_first")`.

### Test 6: `test_db_error_fallback`
- **Setup:** Mock `db.insert()` or query to raise an exception.
- **Assertion:** `select_template` logs warning and returns `(base_prompt, "base")`.
- **Assertion:** `record_outcome` logs warning and does not raise.

### Test 7: `test_record_outcome_invalid_template_id`
- **Setup:** Call `record_outcome(kind="x", template_id="unknown_template", merged_first_try=True)`.
- **Assertion:** No exception raised. DB record created with `template_id="unknown_template"`. Future `select_template` calls can score it via UCB1 if it appears in results.

---

## Acceptance Criteria

### Correctness
- [ ] UCB1 score formula is correct: `mean_reward + sqrt(2 * ln(N) / n_trials)` for tried arms.
- [ ] Untried arms always score higher than any tried arm (tested via `test_ucb_prefers_untried_arm`).
- [ ] Variant tag prepend/dedup is idempotent (tested via `test_variant_tag_idempotence`).
- [ ] `merge-duplicates` accumulates `total_reward` and `n_trials`, not replaces (tested via `test_record_outcome_accumulates_on_duplicate`).

### Error Handling (Fail-soft per project conventions)
- [ ] `select_template` never raises; always returns valid `(str, str)` tuple.
- [ ] `record_outcome` never raises; always returns `None`.
- [ ] All DB errors are logged with `logging.warning(...)` including module name and method name.
- [ ] Graceful fallback on error: `select_template` → `(base_prompt, "base")`, `record_outcome` → silent swallow.

### Thread-Safety & Concurrency
- [ ] All DB operations delegate to `db` singleton, which provides its own locking.
- [ ] No module-level mutable state besides the DB connection.
- [ ] Safe to call from multiple threads concurrently.

### Performance & Scale
- [ ] Handle up to **100 templates per kind** without N+1 queries (single `WHERE kind=...` query per `select_template` call).
- [ ] Response time < 10ms in nominal case (single DB query + UCB1 calculation).
- [ ] No memory leaks or unbounded state accumulation in the module.

### Cold-Start Behavior
- [ ] On empty DB, `select_template` returns templates in `TEMPLATE_IDS` order deterministically.
- [ ] After cold-start, subsequent calls follow UCB1 ranking.

### Invalid Inputs
- [ ] `template_id` not in `TEMPLATE_IDS` is not rejected; allows dynamic experimentation.
- [ ] `kind=""` (empty string) is a valid kind (no special case needed).
- [ ] `base_prompt=""` (empty string) is valid; variant tags prepended normally.

### Observability
- [ ] All errors logged with `PromptEvolver` prefix so operators can grep logs.
- [ ] No debug-level spam; only warnings on actual failures.

---

## Implementation Notes

### Module Structure
```python
import logging
from runner import db  # singleton import (resolved import ambiguity)

TEMPLATE_IDS = ["base", "chain_of_thought", "edit_first"]

def select_template(kind: str, base_prompt: str) -> tuple[str, str]:
    # ... implementation

def record_outcome(kind: str, template_id: str, merged_first_try: bool) -> None:
    # ... implementation
```

### Why No Class
Per project conventions (module-level singletons), functions delegate to a shared singleton (the `db` module), not instance methods. A bare module with functions is simpler and follows the pattern seen in other parts of the codebase.

---

## Confidence & Rationale

| Ambiguity | Resolution | Confidence | Rationale |
|-----------|-----------|-----------|-----------|
| Intent | UCB1-based template optimizer | 0.95 | Spec title and methods clearly point to bandit; only text was corrupted |
| Cold-start | Return templates in `TEMPLATE_IDS` order | 0.90 | Deterministic discovery is standard in RL; avoids randomness |
| Untried tiebreaker | Position in `TEMPLATE_IDS` | 0.85 | Deterministic, testable; no spec guidance so convention-driven |
| merge-duplicates | Sum rewards, increment trials | 0.98 | Spec explicitly says "merge-duplicates" and contrasts with "upsert"; accumulation is the obvious meaning |
| DB import | `from runner import db` | 0.90 | Project convention: module-level singletons, not direct imports |
| Variant tag | Detect & skip or replace | 0.80 | Idempotence is a safe default; prevents double-tagging |
| N=0 edge case | Untried-arm check before formula | 0.95 | Spec already handles this; untried score = ∞ |
| Test 3–5 | Complete with clear assertions | 0.85 | Spec intent inferred from implementation requirements |

