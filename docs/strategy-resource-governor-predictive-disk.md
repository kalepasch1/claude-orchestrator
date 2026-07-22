# Strategy: resource_governor predictive disk monitoring

**Date:** 2026-07-18
**Category:** Plan / documentation

## Current State
`_predicted_disk_pct()` fits a linear trend to the last 20 `resource_events`
disk readings and predicts when `DISK_HARD` will be breached. The prediction
window defaults to `PREDICT_DISK_WINDOW_H` (2 hours).

## Observations
1. The function requires at least 4 data points to produce a prediction.
   With the default event emission rate, this means ~4 govern() cycles
   (~20 minutes at 5-min intervals) before predictions are available after
   a fresh start.
2. Linear extrapolation works well for steady-state growth but may
   over-react to burst patterns (e.g., a large git clone that triggers
   immediate cleanup).
3. The `horizon_seconds` parameter is accepted but never passed by callers,
   so the default 2-hour window is always used.

## No change recommended
Current implementation is appropriate for the workload profile.
