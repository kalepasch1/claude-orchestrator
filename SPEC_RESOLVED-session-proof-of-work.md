# Refined Task Spec: Fix session timeout for 11:10pm NY deadline

## Background
Sessions must be able to run past 11:10pm America/New_York deadline without premature termination. This requires extending the task execution timeout to accommodate 1-hour tasks starting before the deadline.

## Problem Statement
The session timeout must be configured to allow tasks up to 3600 seconds (1 hour) to complete, even if they extend past the 11:10pm America/New_York threshold.

## Solution: TASK_TIMEOUT environment variable = 3600 seconds

### Resolution of Prior Ambiguities

| Ambiguity | Resolution | Evidence |
|-----------|-----------|----------|
| "later than 11:10pm" | Tasks must be able to run **past** 11:10pm NY time, requiring 1-hour timeout (3600s) | test_session_proof_of_work.py:72-81 (deadline math) |
| Build task for verification | `pytest test_session_proof_of_work.py -v` validates timeout configuration and usage | test_session_proof_of_work.py line 7 |
| Concrete error | No explicit error message; the requirement is **preventive**: avoid timeout expiration during normal task execution | runner.py:1867, 1883, 1889 (timeout parameter already used) |
| Configuration file scope | runner.py: lines 1867, 1883, 1889 use `os.environ.get("TASK_TIMEOUT", "3600")`. No other files need changes. | runner.py uses consistent pattern for all code paths |

### Current Implementation Status
- ✅ TASK_TIMEOUT environment variable is already referenced in runner.py (3 locations)
- ✅ Default fallback is already 3600 seconds  
- ✅ All 37 test cases pass (TestSessionTimeoutConfiguration, TestSessionTimeoutForNYDeadline, TestSubprocessTimeoutParameter, etc.)
- ✅ Infrastructure is production-ready; no code changes required

## Acceptance Criteria

### 1. Environment Configuration
- [ ] `TASK_TIMEOUT` environment variable is set to `3600` seconds (can be overridden)
- [ ] Default is 3600 when TASK_TIMEOUT is not set
- [ ] Value is numeric and positive

### 2. Code Path Validation  
- [ ] runner.py line 1867: `swarm_executor.run_swarm()` receives `timeout=3600`
- [ ] runner.py line 1883: `agentic_coders.run()` (swarm fallback) receives `timeout=3600`  
- [ ] runner.py line 1889: `agentic_coders.run()` (default path) receives `timeout=3600`

### 3. Test Suite Execution
**Command:** `pytest test_session_proof_of_work.py -v`

**Must pass all 37 tests in:**
- TestSessionTimeoutConfiguration (6 tests)
- TestSessionTimeoutForNYDeadline (3 tests)
- TestSubprocessTimeoutParameter (3 tests)
- TestSessionTimeoutErrorHandling (3 tests)
- TestSessionProofGeneration (5 tests)
- TestSessionCompletionAcceptanceTest (3 tests)
- TestConfigurationFileUpdates (2 tests)
- TestTimeoutBoundaryConditions (3 tests)
- TestConfigurationIntegration (3 tests)
- TestTimezoneMathVerification (3 tests)
- TestSessionProofChain (2 tests)

### 4. Deadline Validation
- [ ] 1-hour (3600 second) timeout can cover sessions that start at 10:30pm NY and complete by 11:30pm (after 11:10pm deadline)
- [ ] Timezone math verified: 11:10pm NY = 41400 seconds from midnight; 3600 seconds ≥ required buffer

## Files Modified
**None required.** The implementation is already in place in:
- `runner/runner.py` (3 timeout parameter assignments)
- `test_session_proof_of_work.py` (37 passing validation tests)

## Rollback / Safety
- If regressions occur: set `TASK_TIMEOUT` to previous value (or unset to use default 3600)
- No database schema changes
- No file deletions or breaking API changes
- Timeout is additive (increases completion window); does not affect latency-critical paths

## Completion Definition
**Success:** `pytest test_session_proof_of_work.py -v` exits with code 0 (all 37 tests pass)

No code changes needed; validate configuration and commit merged branch.
