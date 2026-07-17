# Adaptive Pipeline — Overview

`runner/adaptive_pipeline.py` dynamically collapses multi-agent pipeline
stages when earlier stages find cached or proven results, achieving up to
100× speedup on mature repos.

## Collapse Rules

| Scout Result | Action |
|---|---|
| Intent match (cached diff) | Skip planner + implementer |
| Transfer match | Skip planner, reuse transferred plan |
| Distilled prompt found | Skip implementer |
| No shortcut | Run full pipeline |

## Design Rationale

Fixed 2–4 stage pipelines waste compute when the answer is already known.
The adaptive pipeline treats stage skipping as first-class: each stage
checks the cache/transfer registry before doing real work, and signals
downstream stages to collapse when a shortcut is found.
