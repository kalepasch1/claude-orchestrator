# canary-ollama-3-47

Canary verification: added docstring clarification for `should_skip` threshold.

## Change
- `tests/test_failure_forecast.py`: clarified that the consecutive-failure
  threshold is 3 (not configurable) and documented the state values that
  count as failures (`BLOCKED`, `FAILED`, `ERROR`).
