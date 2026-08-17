# Refined Specification: Cross-Project Dependency Resolution

**Date:** 2026-08-16  
**Status:** ACTIVE (repair continuation)  
**Original Task Slug:** `orch-cross-project-depends`  
**Repair Category:** Merge conflict resolution + implementation completion

---

## Executive Summary

Extend the dependency resolver in `runner/planner.py` and `runner/enqueue_task.py` to support cross-project task references of the form `project_name:task_id` while preserving backward compatibility for bare task IDs that remain project-local. This unblocks coordinated extraction of shared CANDIDATE modules into a single shared package across multiple projects (beethoven, apparently, and others) in a single wave.

---

## Ambiguity Resolutions

### 1. Task Class Metadata: `legal (need 9, risk legal_posture)`

**Resolved As:** Task classification with priority and risk signals.

- **Task Class:** `legal` — indicates this task touches legal/compliance boundaries (licensing, intellectual property, custody of shared modules).
- **Priority Signal:** `need 9` → Priority level 9 (on scale 1–10, where 10 is highest). Indicates high-priority legal review.
- **Risk Classification:** `legal_posture` → Regulatory/licensing posture; affects whether owner-only gate applies.

**Application to This Task:**  
Cross-project dependency resolution touches **custody** (managing dependencies across project boundaries) and **licensing** (shared modules must respect license compliance across projects). **No transmission/advice aspects.**

---

### 2. Model/Route Specifiers: `qpd leader q=7.66`

**Resolved As:** Quality-based routing and lead route designation.

- **QPD** = Quality/Performance/Decision score (dimensionless, 0–10 scale, higher = more capable/suitable).
- **leader** = Designated as the lead/primary route for this orchestration phase.
- **q=7.66** = Quality score 7.66; route is suitable for complex legal/strategy reasoning.

**Application to This Task:**  
Model selection is already determined in original spec (claude-fable-5 for agentic coding). QPD scores guide load balancing across cloud routes but do not change the task definition.

---

### 3. Operator Feedback: Truncated Remediation Context

**Original (Truncated):**  
> "Production telemetry from the remediation loop shows that a fixed 30-minute cadence results in a median remediation lag of 17 minutes, while…"

**Resolved As:** Acknowledged incomplete; represents a separate observability/telemetry concern outside the scope of this task.

**Decision:** This operator feedback is noted for future observability/monitoring work but **does not constrain the dependency resolver specification.** Do not block task on this signal.

---

### 4. Legal Gate Trigger Conditions

**Original Specification:**  
> "legal gate: owner-only when the change would force licensing/registration/custody/transmission/advice or needs a secret"

**Resolved As:** For this cross-project dependency resolver change:

- ✅ **Custody:** APPLIES — managing dependencies across project boundaries is a custody concern.
- ✅ **Licensing:** APPLIES — shared modules imported cross-project must satisfy license compliance.
- ❌ **Registration:** Does NOT apply (no new services/accounts created).
- ❌ **Transmission:** Does NOT apply (no data transmitted between projects at runtime).
- ❌ **Advice:** Does NOT apply (no legal consultation required for code logic itself).
- ❌ **Secrets:** Does NOT apply (dependency resolver uses no credentials).

**Action:** Owner-only gate applies ONLY if the resolved shared modules require legal review (e.g., GPL compliance, patent concerns). Default: **gate applies** unless shared modules are internal/proprietary.

---

### 5. Merge/Build Conflict Details

**Original (Vague):**  
> "recover from the merge/build conflict"

**Resolved As:** This task depends on `orch-tests-first-gate` (both modify dependency resolution logic). The merge conflict is **in the planner.py dependency graph resolution and enqueue_task.py task enqueueing logic**, specifically:

- **File:** `runner/planner.py` — Task decomposition and dependency DAG construction
- **File:** `runner/enqueue_task.py` — Task enqueueing, dependency validation, and database insertion
- **Conflict Source:** Both branches extend the `deps` field handling; merge conflict occurs at lines where bare IDs are expanded or validated.

**Resolution Strategy:** Apply this task's changes AFTER `orch-tests-first-gate` merges; use the test suite to validate no regression.

---

### 6. Truncated Recovery Instructions

**Original (Truncated):**  
> "If the branch/worktree is missing, r…"

**Resolved As:** Apply convention from CLAUDE.md—if the worktree is missing:

1. Recover from `agent/orch-cross-project-depends` branch in git history.
2. Emit a git patch if push fails (ChatGPT sandbox isolation).
3. Use bridge (`tools/chatgpt-bridge/`) to apply patch as an isolated worktree + PR.

---

## Task Definition

### Objective

Extend `runner/planner.py` and `runner/enqueue_task.py` to resolve task dependencies against a **global cross-project task namespace** while preserving backward compatibility.

### Scope

#### Files Modified

| File | Change | Reason |
|------|--------|--------|
| `runner/db.py` | Extend `_done_slugs()` to return both bare slugs (backward compat) and `project_name:slug` qualified entries | Dependency resolution against global namespace |
| `runner/enqueue_task.py` | Parse and pass through `deps` field; validate bare and qualified IDs | Task enqueueing |
| `runner/planner.py` | Update prompt/DAG to generate qualified cross-project deps when needed | Task decomposition |
| `runner/tests/test_cross_project_depends.py` | (Existing; extend coverage) | Validation |

#### Dependency Reference Formats

- **Bare ID (backward-compatible, project-local):** `curation-layer-land`  
  → Resolves against the current project's completed tasks only.

- **Cross-Project ID (new):** `apparently:curation-layer-land`  
  → Resolves against the global task namespace (all projects, state=DONE or MERGED).

- **Mixed Dependencies:** A single task's `deps` list may contain both formats:
  ```json
  {
    "slug": "shared-module-pack",
    "deps": ["contracts", "apparently:curation-layer-land", "local-task"]
  }
  ```

---

## Acceptance Criteria

### A. Backward Compatibility

**MUST:** Old bare-id format `task_id` (without `project_name:` prefix) works identically with zero behavior change or performance regression.

- Bare IDs in existing tasks must resolve as project-local (current behavior).
- No breaking changes to dependency resolution logic for tasks with only bare IDs.
- All existing tests pass without modification.

### B. Cross-Project Resolution

**MUST:** A dependency reference in form `project_name:task_id` resolves against the global task namespace.

- Only tasks in state `DONE` or `MERGED` satisfy a cross-project dep.
- Task remains blocked if cross-project dep does not exist.
- Qualified ID can be mixed with bare IDs in the same `deps` list.

### C. Error Handling & Blocking Behavior

**MUST:** Unknown or unsatisfied dependencies NEVER cause silent/partial execution.

- If a cross-project dep (e.g., `otherproject:missing-task`) is not found, the task stays **BLOCKED**.
- Error is logged with full context (project, task_id, missing_dep).
- Task **never** begins execution with unmet dependencies.
- No fallback to partial/local-only execution.

### D. Global Task Namespace Definition

**Specification:**

- **Type:** In-memory set, populated at startup and refreshed every 60 seconds.
- **Contents:** All tasks with state `DONE` or `MERGED`, from all projects in the database.
- **Keys:** Set members are strings in two forms:
  - Bare slug: `setup-ci` (from tasks.slug, all projects)
  - Qualified: `beethoven:setup-ci`, `apparently:curation-layer-land`, etc.
- **Refresh Mechanism:** `db._done_slugs()` uses thread-safe lock and TTL-based caching.
- **Scope:** Shared across all `enqueue_task.py` calls in the current runner process and all dependency claims in `runner/claim_task.py` or equivalent.
- **Failure Mode (Graceful Degradation):** If project name lookup fails (e.g., DB connection issue), bare slugs still appear in the set; qualified entries are omitted.

### E. Validation Rules

**MUST:** Apply these rules when validating a task's `deps` list:

1. **Bare ID Format:** Alphanumeric + hyphens only; matches `^[a-z0-9-]+$`.
2. **Qualified ID Format:** `project_name:task_id`; each component matches alphanumeric + hyphens; matches `^[a-z0-9-]+:[a-z0-9-]+$`.
3. **Cross-Project Whitelist:** Any project may depend on any other project's task (no explicit whitelist).
4. **Dependency State Constraint:** Cross-project deps must reference tasks in `DONE` or `MERGED` state only; bare local deps have no state constraint (follow planner rules).
5. **Circular Dependency Detection:** The planner's DAG validator must detect cycles (bare OR qualified IDs); reject task with diagnostic error.

### F. Test Coverage & Proof Criteria

**Test File:** `runner/tests/test_cross_project_depends.py`

**Minimum Test Cases (must include):**

1. **Bare Local ID Resolution**
   - Bare dep in done set → claimable
   - Bare dep NOT in done set → blocked

2. **Cross-Project ID Resolution**
   - Qualified dep `project:id` in done set → claimable
   - Qualified dep `project:id` NOT in done set → blocked
   - Unknown project (qualified dep) → blocked

3. **Unknown Reference Handling**
   - Bare ID not in done set → blocked (not silently run)
   - Qualified ID for non-existent project:task → blocked
   - Mixed deps (some found, some not) → BLOCKED (all-or-nothing)

4. **Mixed Local and Cross-Project**
   - Single task with both bare and qualified deps → all must be satisfied

5. **Edge Cases**
   - Empty deps list → always claimable
   - Malformed qualified ID (missing colon, invalid chars) → rejected before DB insert
   - Project name lookup failure (DB down) → bare slugs still present; qualified entries omitted; task behavior graceful

6. **Backward Compatibility**
   - Existing tasks with bare-only deps work unchanged
   - No performance regression (<5% latency increase on dependency checks)

**Proof Criteria:**

```bash
python -m pytest runner/tests/ -q
```

**Exit Status:** 0 (all tests pass)

**Coverage:**  
- New resolver logic: ≥85% code coverage (measured via pytest-cov)
- Includes test_cross_project_depends.py (all new test cases above)
- No skipped tests; all must pass

**Example Invocation:**
```bash
cd runner
python -m pytest runner/tests/test_cross_project_depends.py -v --cov=db --cov-report=term-missing
```

---

## Implementation Notes

### Fail-Soft Error Handling (Per Convention)

Per CLAUDE.md: "Errors during code execution or database queries do not wedge the runner; they are swallowed to prevent crashes."

**Application:**

- If project name lookup fails (DB connection error), continue with bare slugs only (graceful degradation).
- If circular dependency check fails, log error and reject task; do not crash the enqueuer.
- If parsing a qualified ID fails, reject with clear diagnostic (malformed format); do not raise unhandled exception.

### Module-Level Singleton Pattern (Per Convention)

The global task namespace is managed by `db._done_slugs()`, a module-level function that delegates to a thread-safe singleton cache (`_done_cache`). Callers access it via `db._done_slugs()`, not by managing cache state directly.

**Cache Properties:**
- Thread-safe: guarded by `_done_cache_lock`
- TTL-based refresh: 60-second default (ORCH_DONE_CACHE_TTL env var, fleet-pushable)
- Defensive file/DB I/O: Catch `ConnectionError`, `FileNotFoundError` separately; return sensible defaults

---

## Coordination Rules

### Merge Strategy

1. This task depends on `orch-tests-first-gate` (both modify planner.py/enqueue_task.py).
2. Apply changes to a feature branch `agent/orch-cross-project-depends-<hash>`.
3. After `orch-tests-first-gate` merges to `master`, rebase this branch to resolve merge conflict.
4. Run full test suite before merging.
5. Auto-merge to `master` after verification; production release via batch train.

### Reuse & Precedent

**Prior Similar Work:**
- `orch-tests-first-gate` — also modifies planner.py/enqueue_task.py; coordinate merge order.
- `dependency_stub.py` — existing cross-project dependency handling for branch resolution; reference for patterns.
- `test_dependency_release.py` — existing cross-project task validation patterns.

### Queued Work

Do NOT delete or overwrite:
- Any tasks currently in queue (QUEUED, WAITING, BLOCKED, DECOMPOSED states).
- Leave recovered work in queue until shipped (per coordination rule in original spec).

---

## Legal Gate & Owner Review

**Gate Status:** ✅ **APPLIES**

**Reasoning:**
- Task touches **custody** (dependency resolution across project boundaries).
- Task touches **licensing** (shared modules must comply across projects).
- Extraction to shared package has IP/licensing implications.

**Owner Review Required:** Yes. Verify that shared modules being extracted do not violate any internal licensing agreements or external open-source licenses (GPL, Apache, MIT, etc.).

---

## Delivery

### Outputs

- Modified files: `runner/db.py`, `runner/enqueue_task.py`, `runner/planner.py`
- New/extended test file: `runner/tests/test_cross_project_depends.py` (already exists; extend as above)
- This refined spec (documentation)

### Proof of Completion

```bash
python -m pytest runner/tests/ -q
# Expected: Exit code 0, all tests pass
```

### Success Criteria

✅ Proof exits 0  
✅ All test cases in test_cross_project_depends.py pass  
✅ No regression in existing tests  
✅ Code review by owner (legal gate)  
✅ Auto-merge to master  
✅ Production release via batch train  

---

## References

- **CLAUDE.md:** Fail-soft error handling, module-level singleton pattern, worktree convention
- **enqueue_task.py:** Task enqueueing, dependency field handling (lines ~160–170)
- **planner.py:** Dependency DAG decomposition (lines ~40–50, _apply_tdd_gating example)
- **db.py:** `_done_slugs()` function, global task namespace implementation
- **Merged branch patterns:** See MEMORY.md → [Merged branch task taxonomy]
- **Existing test patterns:** runner/tests/test_dependency_release.py, test_dependency_stub.py

