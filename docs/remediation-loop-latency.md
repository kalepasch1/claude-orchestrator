# Remediation Loop Latency

## Context

Operator feedback identified a measured bottleneck in the application's
response time during the remediation loop, causing potential service
disruptions.

## Root Cause

When the remediation loop retries a failed task, each iteration performs
a full pipeline re-evaluation (triage → strategy → code → QA). If the
upstream model endpoint is slow or rate-limited, the synchronous wait
compounds across retries.

## Mitigation Checklist

1. **Timeout cap** – ensure `ORCH_REMEDIATION_TIMEOUT_S` (default 300)
   is set; the loop aborts after this ceiling rather than blocking the
   runner indefinitely.
2. **Exponential back-off** – the retry delay doubles each attempt
   (1 s → 2 s → 4 s …) to avoid thundering-herd effects against shared
   model endpoints.
3. **Circuit breaker** – after 3 consecutive failures on the same coder
   route, the task is re-queued for a different coder rather than
   retrying the same path.

## Monitoring

Check `fleet_config.COWORK_EXECUTOR_V6_LAST_RUN` for the latest
heartbeat timestamp. A gap longer than the scheduled interval indicates
the executor stalled — likely inside a remediation loop.
