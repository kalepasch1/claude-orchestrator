# Cross-Learning Model Routing

Documents how the orchestration pipeline selects and evaluates coders
based on historical outcome signals.

## Signal Collection

Each task execution records:
- **Merge rate** — did the branch get merged?
- **Test-pass rate** — did tests pass before merge?
- **Cost** — API/compute cost for the coder run
- **Model identity** — which model produced the output

## Learned Routes

The pipeline maintains per-task-class routing preferences:
```
pipeline_scout     -> local:llama3.2:3b     (q=4.7)
completion         -> local:llama3.2:3b     (q=6.45)
meta_loop_improve  -> local:codestral:22b   (q=7.7)
build_fix          -> local:llama3.1        (q=7.7)
```

Routes are updated when a model consistently outperforms the current
leader on quality-per-dollar (QPD) for a given task class.

## Operator Feedback Loop

Operators can inject feedback via the `cross-learning context` field:
- **strategy** — pipeline-level adjustments
- **other** — ad-hoc observations (e.g., false-positive rate)

Feedback is weighted by severity (high > medium > low) and surfaced
to the strategy planner during the next task decomposition.

## Canary Routing

Canary tasks test new models by assigning them small, safe changes
(doc clarifications, test hygiene) and comparing outcomes against
the incumbent. A canary that merges cleanly and passes tests earns
QPD credit for its model.
