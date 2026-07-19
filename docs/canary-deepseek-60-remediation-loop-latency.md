# Remediation Loop Latency — Monitoring Guide

## Context

Operator feedback flagged a measured bottleneck in the application's response
time during the remediation loop, causing potential service disruptions.

## Where latency accumulates

1. **`agentic_repair.py`** — retries against external model APIs add wall-clock
   time proportional to `attempt * backoff`.
2. **`verify.py`** — cheap-model diff review blocks the pipeline until a
   pass/fail verdict returns.
3. **`runner.py` main loop** — sequential task polling means one slow task
   stalls the next claim cycle.

## Recommended observation points

- Log `time.monotonic()` deltas around each model call in `agentic_repair.py`.
- Check the `cost_ledger` for tasks whose wall-clock exceeds 2× their model
  latency — the gap is pipeline overhead.
- Review `anomaly.py` spike thresholds: the default 1.75× baseline may mask
  slow-burn regressions that stay just under the alert line.

## Non-goals

This document does NOT propose changing secrets, dependencies, billing logic,
or product behavior. It is a reference for operators investigating latency.
