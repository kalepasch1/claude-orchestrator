# Anomaly Detection — Alerting Thresholds

## Overview
`runner/anomaly.py` monitors three vitals for the orchestrator fleet:

| Metric | Description | Default spike multiplier |
|--------|-------------|--------------------------|
| `fail_rate` | Fraction of recent tasks that failed tests | 1.75× baseline |
| `rate_limit_rate` | Fraction of recent tasks that hit rate limits | 1.75× baseline |
| `cost_per_task` | Average USD cost per task in the recent window | 1.75× baseline |

## Configuration (env vars)
- `ANOMALY_RECENT` — size of the recent-task window (default: 30)
- `ANOMALY_SPIKE` — multiplier threshold vs trailing baseline (default: 1.75)

## Behaviour
- Baseline is computed from tasks `[RECENT..300]` in the outcomes table.
- If fewer than `RECENT * 2` rows exist, the check returns `ok: true` (not enough data).
- Each triggered alert creates an approval card in the `approvals` table for operator review.
