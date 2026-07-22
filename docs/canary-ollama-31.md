# canary-ollama-31

Canary verification: documented MockDB injection pattern for test_failure_forecast.

## Change
- Noted the `_db` keyword-arg injection pattern used by `should_skip` so future
  test authors can follow the same approach when adding new forecast tests
  without needing to patch module-level imports.
