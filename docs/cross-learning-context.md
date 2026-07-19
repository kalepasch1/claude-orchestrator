# Cross-Learning Context

## What It Is

The orchestration pipeline contract includes a `cross-learning context`
block that feeds outcome history from recent tasks back into the prompt
for strategy planning and coder routing.

## Fields

- **recent outcome signal** – rolling window of merged/test-pass counts,
  total spend, and which models were involved. Helps the strategy planner
  avoid routes that have been failing.
- **learned route** – per-task-class best-performing model and its
  quality score (`q`). The planner prefers these routes when the task
  class matches.
- **operator feedback** – free-text note from the operator (severity /
  category). Signals systemic issues the planner should factor in (e.g.,
  latency bottlenecks, cost overruns).

## How It Is Generated

`runner.py` computes the block at task-creation time by querying the
`tasks` table for the most recent N outcomes in the same project. The
learned routes come from `coder_quality` aggregates.

## Using It Safely

- Cross-learning is **informational** — it biases routing but never
  hard-blocks a coder.
- A model with q=0 has no data yet, not proven-bad quality.
- Operator feedback with severity "medium" or higher triggers an
  advisory log line but does not auto-block the flagged route.
