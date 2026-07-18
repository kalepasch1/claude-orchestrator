# Anomaly Detection — Operator Guide

The `runner/anomaly.py` module monitors fleet health by comparing recent task
outcomes against a trailing baseline. It is stateless and reads directly from
the `outcomes` table in Supabase.

## Metrics tracked

| Metric | What it measures | Default spike threshold |
|---|---|---|
| Failure rate | % of tasks ending in non-DONE states | 1.75x baseline |
| Cost per task | Average USD spend per completed task | 1.75x baseline |
| Rate-limit frequency | How often tasks hit provider rate limits | 1.75x baseline |

## Configuration

All tunables are environment variables (or `fleet_config` keys):

- `ANOMALY_RECENT` (default `30`) — size of the recent window (last N tasks)
- `ANOMALY_SPIKE` (default `1.75`) — multiplier above baseline that triggers an alert

## Running

Designed to run on a schedule (e.g. hourly via cron or the orchestrator loop).
No persistent state — each run computes fresh from the database.

```bash
python3 runner/anomaly.py
```

## Alert flow

When a spike is detected, the module files an approval card so the operator
can investigate before the anomaly compounds into a larger cost or stall.
