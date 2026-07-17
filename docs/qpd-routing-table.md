# QPD (Quality-Per-Dollar) Routing Table

## Purpose
Maps task categories to the best-performing AI vendor based on historical
quality scores and cost. Updated automatically as canary and production
tasks complete.

## Key Fields
- **route** — task category (e.g., `build_fix`, `completion`, `pipeline_scout`)
- **model** — vendor:model string (e.g., `local:llama3.2:3b`)
- **q** — quality score (0–10 scale, exponential moving average)
- **cost** — average USD cost per task for that route+model pair
- **n** — sample count feeding the quality estimate

## How It's Used
The strategy planner selects the cheapest model whose quality score
exceeds the minimum threshold for the task's risk tier.
