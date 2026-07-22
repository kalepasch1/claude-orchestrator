# canary-ollama-4-51

Canary verification: documented aggregate_cross_portfolio return schema.

## Change
- Clarified the expected return shape of `aggregate_cross_portfolio` including
  `total_experiments`, `tactics` dict with `apps_tested`, `portfolio_avg_lift_pct`,
  and `per_app` list structure for downstream consumers.
