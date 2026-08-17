# REFINED TASK SPEC: Fix Session Timeout to Allow Completion Before 11:10pm America/New_York

## Problem Statement
The Claude CLI runner (`runner/runner.py`) enforces a subprocess timeout (currently 900 seconds / 15 minutes) that causes long-running build/test tasks to be terminated before completion. Tasks that should finish by 11:10pm America/New_York are timing out before the wall-clock deadline, preventing successful task execution.

## Ambiguity Resolutions

### 1. Meaning of "later than 11:10pm"
**Resolution:** Extend the subprocess timeout **duration** so tasks have enough time to complete their work before the 11:10pm wall-clock deadline. This is NOT about setting a deadline after 11:10pm; it's about giving the runner enough elapsed time to finish before hitting that outer deadline.

### 2. Which Session System is Affected
**Resolution:** The subprocess timeout in `runner/runner.py` that controls how long the Claude Code CLI invocation is allowed to run. Specifically:
- Line 1868: `timeout=int(os.environ.get("TASK_TIMEOUT", "900"))`
- Line 1884: Claude CLI invocation with subprocess timeout
- Line 1890: Agentic coder invocation timeout

The timeout is a **process execution timeout** (duration), not a wall-clock deadline.

### 3. Current vs. Target Timeout Values
**Current:** 900 seconds (15 minutes) — default value of `TASK_TIMEOUT` env var
**Target:** 3600 seconds (1 hour) — aligns with the prior patch and allows reasonable task completion time
**Rationale:** Build/test tasks in this codebase frequently exceed 15 minutes; 1 hour is a reasonable ceiling for normal execution.

### 4. Build Task to Verify
**Resolution:** Use the project's standard build/test command detected by `build_gate.detect_build_cmd()` (typically `npm run build && npm run test` or equivalent per project). The runner already auto-detects and runs this at line 473-483. Verification is implicit in the build gate's success.

### 5. File Locations and Exact Changes
**File:** `/Users/kpasch/Documents/beethoven/claude-orchestrator/runner/runner.py`

**Locations to change:**
- **Line 1868:** Change subprocess timeout for main Claude CLI invocation
- **Line 1884:** Change timeout for agentic coder fallback invocation  
- **Line 1890:** Change timeout for second agentic coder retry
- **Environment variable:** Default `TASK_TIMEOUT` to 3600 instead of 900, or keep code reading from env and let operator set `export TASK_TIMEOUT=3600` before running

**Changes required:**
Replace all instances of:
```python
timeout=int(os.environ.get("TASK_TIMEOUT", "900"))
```
with:
```python
timeout=int(os.environ.get("TASK_TIMEOUT", "3600"))
```

---

## Acceptance Criteria

### Functional Acceptance
1. **Timeout value set correctly**: Verify `runner.py` has `TASK_TIMEOUT` default of 3600 seconds
2. **Subprocess execution**: Run a build task that takes 20-45 minutes and confirm it completes without timeout
3. **Before 11:10pm wall-clock**: Confirm task starts early enough (before ~10:10pm ET) to finish within 1 hour before deadline
4. **Log verification**: Check `run_logs` table in Supabase shows "timeout" NOT appearing in level/message for completed tasks

### Regression Testing
1. **Short tasks still complete**: Tasks under 5 minutes still complete successfully (no regression)
2. **No spurious timeout kills**: A task that takes 45 minutes completes; it should NOT be killed at 15 minutes
3. **Error messages unchanged**: Timeout errors (when they DO occur) still report clearly with "timeout" in state/note

### Timezone Handling
- **Scope:** No timezone-aware logic needed in the code itself
- The 11:10pm deadline is an **operational constraint** (when the task queue shuts down), not a code-enforced constraint
- The subprocess timeout is a **duration**, not wall-clock aware
- Operator is responsible for starting tasks early enough to complete before 11:10pm ET

### Configuration Persistence
- **One-time fix:** Change the default in the source code (not a per-run config)
- **Operator override:** Operators can still set `export TASK_TIMEOUT=<seconds>` before `python3 runner.py` if they need different timeouts
- **Future runs:** All future runner invocations inherit the new 3600s default

---

## Implementation Strategy

1. **No refactoring:** Keep the existing code structure; only change the numeric default
2. **Preserve error handling:** The timeout exception handling at lines 1893-1900 stays unchanged
3. **No dependency changes:** This is a pure configuration change
4. **No DB migration:** `TASK_TIMEOUT` is already env-var based; no schema changes needed

---

## Test Plan

### Before Merge
1. Run a test task that takes 30+ minutes and verify it completes
2. Confirm `run_logs` shows no spurious timeout errors for that task
3. Run a fast task (< 2 min) and confirm it still completes quickly
4. Check that `TASK_TIMEOUT` env var override still works (set to 7200, verify task honors it)

### Verification Evidence
- Green test suite: `pytest runner/tests/test_*.py` passes
- Supabase `run_logs` table shows no timeout entries for completed tasks
- Task state in Supabase shows "DONE" (not "TIMEOUT" or "RUNNING" after deadline)

---

## Why This Task Failed Before

**Prior patch analysis:** The `agent/session-proof-of-work` branch (last commit 435ded84) attempted this fix but introduced **unrelated deletions** in the same `runner.py` file:
- Removed `stderr_digest` import
- Removed `_is_closure_refusal()` function (breaking error handling)
- Removed error-handling logic in `set_state()` 
- Changed `stderr_digest.digest()` to raw string slicing

These deletions caused **merge conflicts** after 4 rebase attempts. The **root cause:** mixing a small timeout fix with large refactoring in the same commit.

**Correct approach:** Commit ONLY the timeout default change (3 lines), leaving all other code untouched. The prior refactoring should be a separate task/branch.

---

## Success Criteria Summary

- [ ] `runner.py` lines 1868, 1884, 1890 all use `"3600"` as default
- [ ] Build task (30+ min) completes without timeout
- [ ] No "timeout" log entries for successful tasks
- [ ] Env var override (`TASK_TIMEOUT=<seconds>`) still works
- [ ] Commit is mergeable to master without conflicts
- [ ] Tests pass

---

## Related Files (For Reference)
- Config source: `runner/runner.py` lines 1860–1900 (subprocess invocation + timeout handling)
- Log destination: Supabase `run_logs` table (auto-written by `emit_task_log()`)
- Build gate: `runner/build_gate.py` (auto-detects build command per project)
- Monitoring: Supabase dashboard filters on `level='timeout'` to track timeout events
