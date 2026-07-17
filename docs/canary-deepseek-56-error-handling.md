# Error Handling Inventory — action_runner.py

## Current Pattern

`runner/action_runner.py` uses fail-soft error handling per project
conventions. Errors during code execution or database queries are
swallowed to prevent runner crashes.

## Observation

The fail-soft pattern correctly prevents wedging but may silently
discard actionable diagnostics. Consider adding structured error
counters (e.g. `action_runner_errors_total`) to the fleet heartbeat
so operators can detect silent failure trends without breaking
fail-soft guarantees.
