# canary-deepseek-27

Canary verification: added edge-case test for `_lift` with negative-rate guard.

## Change
- `tests/test_cross_portfolio_analytics.py`: added `test_lift_negative_rate_guard`
  to verify `_lift` handles edge case where control_rate equals 1.0 (division
  safety) and very small deltas near zero.
