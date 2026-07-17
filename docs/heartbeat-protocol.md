# Heartbeat Protocol

The executor writes a heartbeat to `fleet_config` after each batch
loop. This lets monitoring systems detect whether the executor is
alive and processing work.

## Heartbeat payload

Key: `COWORK_EXECUTOR_V6_LAST_RUN`

```json
{
  "ts": "2026-07-17T12:00:00Z",
  "claimed": 5,
  "done": 5
}
```

## Staleness detection

If no heartbeat has been written for longer than the zombie-release
window (90 minutes), external monitors can assume the executor session
has ended or crashed.
