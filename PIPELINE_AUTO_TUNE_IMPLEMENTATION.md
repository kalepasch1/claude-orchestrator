# Pipeline Auto-Tuning Implementation

## Overview
Implemented metric-driven pipeline auto-tuning for the compounding engine to minimize idea→prod time. The system measures per-stage cycle-time and first-try-yield, automatically tuning pipeline gates, model selection, and batching based on real outcomes.

## Architecture

### Metric Collection (`improvement_measure.py`)
**New function: `stage_metrics()`**
- Reads completed (MERGED) tasks and their outcomes
- Calculates two key metrics per project/kind over rolling windows (5, 30, 90 days):
  - **cycle_time**: seconds from task creation to merge (completion)
  - **first_try_yield**: percentage of tasks that succeeded on first attempt (remediation_count == 0)
- Aggregates and persists to `stage_metrics` table (upsert, so creates table if not exists)
- Runs daily as part of `improvement_measure.run()`

**Data schema:**
```
stage_metrics (auto-created):
  - project_id: str
  - kind: str (build, research, etc.)
  - window_days: int (5, 30, or 90)
  - avg_cycle_time_seconds: float
  - first_try_yield_pct: float (0-100)
  - sample_count: int
  - updated_at: timestamp
```

### Auto-Tuning Logic (`meta_loop.py`)
**New functions:**
- `_stage_metrics_summary()`: Reads 30-day stage_metrics for all projects
- `_read_tuning_state()`: Loads active tuning decisions from resource_events
- `_plan_auto_tune_decisions()`: Analyzes metrics and proposes safe tuning actions
- `_log_tuning_decision()`: Records decisions to resource_events for audit trail

**Tuning Decisions:**
1. **Gate selection** (plan_stage):
   - Trigger: first_try_yield < 60%
   - Action: Route 10% of low-risk tasks to bypass build gate
   - Uses: existing llm-gating-policy infrastructure
   
2. **Model rotation** (cowork_stage):
   - Trigger: Cycle time increased >15% in last 5 days (regression detection)
   - Action: Rotate back to cheaper models in the selection mix
   - Uses: existing model_policy infrastructure

3. **Batch sizing** (future):
   - Placeholder for increasing batch size when reuse_first match rate > 85%
   - Uses: existing reuse_first infrastructure

**Guardrails:**
- `ORCH_TUNE_MIN_SAMPLES` (default 50): Minimum samples before tuning
- `ORCH_TUNE_MAX_CHANGE_PCT` (default 15): Maximum change per decision
- Cold-start: No tuning in first 100 tasks (insufficient baseline)
- Decision logging: All tuning decisions logged to resource_events with decision_id for traceability

### Decision Lifecycle
1. **Planning**: `_plan_auto_tune_decisions()` analyzes metrics
2. **Validation**: Guardrails ensure decisions are safe
3. **Logging**: Decisions written to `resource_events` table (kind='auto_tune_decision')
4. **Application**: Runner or separate process applies decisions via policy updates
5. **Monitoring**: Decisions tracked with status (active, rolled_back, etc.)
6. **Rollback**: If subsequent 50 tasks show >10% regression, auto-flip decision

## Configuration

### Environment Variables
```bash
# Enable auto-tuning (default: false)
ORCH_AUTO_TUNE_ENABLE=true|false

# Dry-run mode: log decisions without applying (default: false)
ORCH_AUTO_TUNE_DRYRUN=true|false

# Minimum samples before tuning (default: 50)
ORCH_TUNE_MIN_SAMPLES=50

# Maximum change percentage per decision (default: 15)
ORCH_TUNE_MAX_CHANGE_PCT=15

# First-try-yield threshold for gate tuning (hard-coded: 0.60 = 60%)
# Cycle-time regression threshold (hard-coded: 0.15 = 15%)
# Precedent match threshold for batch sizing (hard-coded: 0.85 = 85%)
```

### Database Tables (Auto-Created)
**stage_metrics**: Aggregated per-stage metrics
- Columns: project_id, kind, window_days, avg_cycle_time_seconds, first_try_yield_pct, sample_count, updated_at
- Upsert key: (project_id, kind, window_days)
- Retention: Keeps rolling 90-day windows

**resource_events**: Existing table, reused for decision logging
- New kind: 'auto_tune_decision'
- detail field: JSON with decision_id, action, metrics, justification

## Testing

### Test Files
1. **test_meta_loop.py** (9 tests):
   - Metric aggregation (stage_metrics_summary behavior)
   - Auto-tune decision firing logic
   - Guardrail enforcement (min samples, max change %)
   - Tuning state management (read/write active decisions)

2. **test_auto_tune.py** (7 tests):
   - Guardrail validation (min samples, max change %)
   - Decision type filtering (only build tasks get gate bypass)
   - Cycle-time regression detection
   - Dry-run mode behavior
   - Integration tests with improvement_measure.stage_metrics()

### Running Tests
```bash
# Run meta_loop tests
python3 -m unittest runner.tests.test_meta_loop -v

# Run auto-tune tests
python3 -m unittest runner.tests.test_auto_tune -v

# Run both
python3 -m unittest discover -s runner/tests -p "test_*tune*.py" -v
```

## Deployment Strategy

### Phase 1: Dry-Run (1 week)
```bash
ORCH_AUTO_TUNE_DRYRUN=true  # Log decisions without applying
```
- Verify metric collection works
- Review logged decisions for validity
- Adjust thresholds if needed

### Phase 2: Limited Rollout (1 week)
```bash
ORCH_AUTO_TUNE_ENABLE=true
ORCH_TUNE_MIN_SAMPLES=100  # Require more samples initially
```
- Apply decisions for <2% of traffic
- Monitor outcome metrics for regression
- Build confidence in decision logic

### Phase 3: Full Rollout
```bash
ORCH_AUTO_TUNE_ENABLE=true
ORCH_TUNE_MIN_SAMPLES=50  # Normal threshold
```
- Deploy to all projects
- Monitor auto_tune_decision events in resource_events
- Track improvement in cycle_time and first_try_yield over 2 weeks

## Verification Checklist

✅ Metric collection (improvement_measure.stage_metrics):
- Reads MERGED tasks and outcomes
- Calculates cycle_time (seconds from creation to merge)
- Calculates first_try_yield (% with remediation_count == 0)
- Aggregates over 5/30/90-day rolling windows
- Persists to stage_metrics table (upsert-safe)

✅ Auto-tuning logic (meta_loop._plan_auto_tune_decisions):
- Loads stage_metrics for 30-day window
- Checks guardrails (min samples, max change %)
- Detects first_try_yield < 60% → propose gate bypass
- Detects cycle_time regression >15% → propose model rotation
- Generates decisions with justification

✅ Decision logging (meta_loop._log_tuning_decision):
- Writes to resource_events (kind='auto_tune_decision')
- Includes decision_id, action, metrics, justification
- Handles errors gracefully (doesn't crash on DB failure)

✅ Dry-run mode (ORCH_AUTO_TUNE_DRYRUN):
- Logs decisions to stdout when enabled
- Does not call _log_tuning_decision
- Allows pre-deployment validation

✅ Tests:
- test_meta_loop.py: 9 tests covering metrics, decisions, guardrails, state management
- test_auto_tune.py: 7 tests covering guardrails, regression detection, integration

## Future Enhancements

1. **Rollback mechanism**: Auto-flip decision if >10% regression detected in next 50 tasks
2. **Batch sizing tuning**: Increase batch size when reuse_first match > 85%
3. **Cross-project learning**: Propagate good tuning decisions across similar projects
4. **Adaptive thresholds**: Tune thresholds themselves based on historical outcomes
5. **Explainability**: Enhanced logging with before/after metrics comparisons

## Known Limitations

1. **Cold start**: Requires 50+ samples before tuning (no guidance in first 100 tasks)
2. **Latency**: Decisions take ~1 day to appear (daily meta_loop schedule)
3. **One-directional**: Tuning decisions can only increase/decrease, not implement new features
4. **No feedback loop yet**: Decisions are logged but not yet applied by runner (needs integration)
5. **Single metric per decision**: Each decision targets one metric (cycle_time XOR first_try_yield)

## Integration Notes

The auto-tuning infrastructure is ready but decisions are NOT YET APPLIED by the runner. To complete:

1. **Gate bypass** (plan_stage): Wire decisions to llm-gating-policy env var
2. **Model rotation** (cowork_stage): Wire decisions to model_policy configuration
3. **Batch sizing** (reuse_first): Wire decisions to batch size parameters

These integrations should read resource_events for active tuning decisions and apply them as runtime policy.

## Audit Trail

All tuning decisions are logged to resource_events with:
- `decision_id`: UUID for tracing across logs
- `action`: What is being tuned (gate_bypass, model_rotation, batch_sizing)
- `metric`: Which metric triggered the decision (first_try_yield, cycle_time)
- `current_value`: The measured metric value
- `threshold`: The threshold that was exceeded
- `justification`: Human-readable reason for the decision
- `status`: active | rolled_back | superseded

This enables full audit, replay, and debugging of the auto-tuning loop.
