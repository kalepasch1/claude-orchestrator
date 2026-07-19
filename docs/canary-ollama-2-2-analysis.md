# Canary Ollama 2-2 — Recovery Backlog Analysis

## Context
Recovery-backlog canary task for ollama-2-2 routing validation.
Original task was cleaned as garbage/non-actionable; this documents
the canary routing path for the ollama 2-2 coder pipeline.

## Coder Routing Observations
- Preflight triage: `local:deepseek-coder-v2:16b` (qpd leader q=7.7)
- Strategy planner: `local:llama3.2:3b` (explore, adaptive probe)
- Agentic coder: `ollama` using `ollama/deepseek-coder-v2:16b`
- QA panel: `local:llama3.2:3b`, `deepseek:deepseek-v4-flash`

## Learned Routes (from cross-learning context)
| Route | Model | Quality |
|---|---|---|
| pipeline_scout | local:llama3.2:3b | 4.7 |
| adaptive_probe | local:llama3.2:3b | 7.7 |
| debate_compress | local:llama3.2:3b | 7.5 |
| build_fix | local:llama3.1 | 7.7 |

## Outcome Signal
Recent batch: 1/12 merged, 1/12 test-pass, $0.00 cost.
Low merge rate (8.3%) indicates routing quality needs improvement
for the ollama pipeline on mechanical task classes.

## Recommendation
The adaptive probe route (q=7.7) shows stronger routing than
pipeline_scout (q=4.7). Consider prioritizing local:llama3.2:3b
for mechanical/recovery tasks when ollama merge rate remains
below 25% threshold.
