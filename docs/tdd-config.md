# TDD Configuration Guide

This document describes configuration keys and behavior for TDD-first (test-driven development) task execution in the Claude Orchestrator.

## Overview

TDD-gating structurally enforces test-driven development in the agent task pipeline:
1. Agent writes **failing tests** + explicit **acceptance criteria** BEFORE implementation
2. Criteria must pass in the pytest build gate (`tdd_gate.py`)
3. Task is marked `DONE` only when all `must_pass_tests` pass

TDD-gating applies to new code tasks only (configurable by task kind).

## Configuration Keys

All configuration keys live in the `fleet_config` table in Supabase and are loaded into environment variables on every orchestrator loop.

### ORCH_TDD_ENABLED
- **Type**: boolean
- **Default**: `false`
- **Description**: Master gate. If false, TDD-gating is completely disabled (no test-write phases injected).
- **How to set**: 
  ```sql
  INSERT INTO fleet_config (key, value) VALUES ('ORCH_TDD_ENABLED', 'true');
  -- or via fleet_control action:
  -- {action: 'reload_config', target: 'all'}
  ```
- **Environment variable**: Also reads `ORCH_TDD_ENABLED=true` if set locally

### ORCH_TDD_TASK_KINDS
- **Type**: CSV string
- **Default**: `feature,new-module`
- **Description**: Comma-separated list of task kind identifiers that require TDD-first execution.
  - Only tasks whose slug/kind matches one of these kinds will have TDD-gating applied
  - Common kinds: `feature`, `new-module`, `refactor`, `security`, `optimization`, `performance`
  - Matching is case-insensitive
- **Examples**:
  - `feature,new-module` — gate only new features and modules (default)
  - `feature,new-module,refactor` — also gate refactors
  - `feature,new-module,security,refactor` — comprehensive TDD
- **How to set**:
  ```sql
  INSERT INTO fleet_config (key, value) VALUES ('ORCH_TDD_TASK_KINDS', 'feature,new-module,security');
  ```

### ORCH_TDD_REQUIRED_KINDS (deprecated)
- **Deprecated**: Use `ORCH_TDD_TASK_KINDS` instead
- For backward compatibility, this key is still read by legacy code paths

## Behavior

### Task-Level Acceptance Criteria

When TDD is enabled for a task, the task's acceptance criteria are structured as:

```json
{
  "acceptance_criteria": {
    "metrics": {
      "latency_ms": "<100",
      "coverage_%": ">=90",
      "memory_mb": "<=512"
    },
    "edge_cases": [
      "empty input",
      "unicode characters",
      "concurrent access",
      "timeout scenario"
    ],
    "must_pass_tests": [
      "test_main",
      "test_edge_cases",
      "test_concurrency"
    ]
  }
}
```

- **metrics** (dict): Measurable outcomes. Keys are outcome names, values are criteria (e.g., `"<100"`, `">=90"`).
- **edge_cases** (list): Explicit scenarios that must pass in tests.
- **must_pass_tests** (list): Test function names that gate task completion. Tests must all pass before task is marked done.

### Test Failure Handling

When `tdd_gate.run_must_pass_tests()` is called during build validation:

1. **All must-pass tests run** via pytest
2. **If all pass**: Task advances to `DONE` status
3. **If any fail**:
   - Test failure is logged to stderr + task record
   - Task is marked `BLOCKED`
   - Operator sees failure in build output
   - Operator must re-queue task or skip TDD for that task

No automatic retry. Operator decides next step.

### Fleet-Wide Propagation

Configuration keys are propagated to all machines via `fleet_control.py`:

1. `fleet_control.load_config()` reads `fleet_config` table
2. Safe keys (prefixed with `ORCH_`, `MAX_PARALLEL`, etc.) are loaded into `os.environ`
3. All runners on the fleet converge to the same config
4. Changes are applied within ~30s (cache TTL in `tdd_gate.py`)

**Safety**: Keys containing `KEY`, `SECRET`, `TOKEN`, `PASSWORD` are rejected.

## Common Configuration Scenarios

### Scenario 1: Enable TDD for New Features Only (Recommended Default)

```sql
INSERT INTO fleet_config (key, value) VALUES 
  ('ORCH_TDD_ENABLED', 'true'),
  ('ORCH_TDD_TASK_KINDS', 'feature,new-module');
```

- TDD is active
- Only applies to tasks marked as `feature` or `new-module`
- Refactors, bug fixes, docs changes are exempt (faster iteration)

### Scenario 2: Comprehensive TDD (All New Work)

```sql
INSERT INTO fleet_config (key, value) VALUES 
  ('ORCH_TDD_ENABLED', 'true'),
  ('ORCH_TDD_TASK_KINDS', 'feature,new-module,refactor,security,optimization');
```

- TDD is active for all new work categories
- Enforces test coverage across the board
- May increase task latency but raises first-try correctness

### Scenario 3: TDD Disabled (Opt-In Per Task)

```sql
INSERT INTO fleet_config (key, value) VALUES 
  ('ORCH_TDD_ENABLED', 'false');
```

- TDD-gating is off fleet-wide
- Operators can still use TDD manually via explicit task kinds
- Default for rapid iteration phases

### ORCH_TDD_MAX_TEST_RUNTIME_S
- **Type**: integer (seconds)
- **Default**: `120`
- **Description**: Maximum wall-clock time for the must-pass test suite before the gate
  times out and marks the task BLOCKED. Prevents runaway or hanging tests from stalling
  the pipeline. Set higher for integration-heavy tasks.
- **How to set**:
  ```sql
  INSERT INTO fleet_config (key, value) VALUES ('ORCH_TDD_MAX_TEST_RUNTIME_S', '180')
  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
  ```

## Integration with Build Gate (tdd_gate.py)

The `tdd_gate.py` module is called during CI build validation:

```python
import tdd_gate

# Read config
if tdd_gate.is_tdd_enabled():
    kinds = tdd_gate.get_task_kinds()
    # Check if task is gated
    if tdd_gate.is_tdd_gated(task.kind):
        # Run must-pass tests
        result = tdd_gate.run_must_pass_tests(test_file, task.acceptance_criteria["must_pass_tests"])
        if result["exit_code"] != 0:
            print(f"TDD gate failure: {result['failed']}")
            sys.exit(1)
```

The gate blocks merge (exit code 1) if any `must_pass_tests` fail.

## Monitoring & Debugging

### Check Current Config

```bash
# Read fleet_config from Supabase
curl -H "Authorization: Bearer $SUPABASE_KEY" \
  "https://PROJECT_ID.supabase.co/rest/v1/fleet_config?select=*" | jq .

# Or check environment on running machine
echo $ORCH_TDD_ENABLED
echo $ORCH_TDD_TASK_KINDS
```

### Clear Cache (Force Immediate Reload)

In Python:
```python
import tdd_gate
tdd_gate.invalidate_cache()
```

Or restart the runner to pick up new config.

### Test the Gate Manually

```bash
python3 runner/tdd_gate.py <<EOF
task_spec = {
  "acceptance_criteria": {
    "metrics": {"latency_ms": "<100"},
    "edge_cases": ["case1"],
    "must_pass_tests": ["test_main"]
  }
}
valid, error = tdd_gate.validate_acceptance_criteria(task_spec)
print(valid, error)
EOF
```

## Quick Reference

| Key | Default | Purpose |
|---|---|---|
| `ORCH_TDD_ENABLED` | `false` | Master gate for TDD-gating |
| `ORCH_TDD_TASK_KINDS` | `build,feature` | Task kinds that require TDD |
| `ORCH_TDD_TIMEOUT_SEC` | `300` | Max seconds for test-write phase |
