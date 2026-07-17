# Pipeline Observability Note — adaptive_pipeline.py

## Current State

`runner/adaptive_pipeline.py` selects model routes based on QPD scores
and cost. Route decisions are logged but not aggregated for trend analysis.

## Recommendation

Add a per-route success-rate counter that persists across loop iterations.
This would enable the QPD learner to weight recent outcomes more heavily
and detect model degradation faster (complement to the existing EMA in
the cross-learning context).
