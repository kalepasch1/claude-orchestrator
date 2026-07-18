# Canary Ollama 3-17 Slice 5 — Recovery Backlog Analysis

## Context
Recovery-backlog canary task for coder routing validation.
Original task was cleaned as garbage/non-actionable; this documents
the canary routing path for the ollama coder pipeline.

## Coder Routing Observations
- Preflight triage: `local:deepseek-coder-v2:16b` (qpd leader q=7.7)
- Strategy planner: `claude:claude-haiku-4-5-20251001` (explore, 6 samples)
- Agentic coder: `ollama` using `ollama/deepseek-coder-v2:16b`
- QA panel: `local:llama3.2:3b`, `deepseek:deepseek-v4-flash`

## Learned Routes (from cross-learning context)
| Route | Model | Quality |
|---|---|---|
| pipeline_scout | local:llama3.2:3b | 4.7 |
| plan | local:nomic-embed-text:latest | 4.7 |
| debate_compress | google:gemini-2.5-flash | 7.4 |
| verify_diff | local:llama3.2:3b | 4.7 |

## Outcome Signal
Recent batch: 0/12 merged, 2/12 test-pass, $0.01 cost.
Low merge rate indicates routing quality needs improvement for
the ollama pipeline on mechanical task classes.

## Recommendation
Consider routing mechanical tasks away from ollama when
recent merge rate is below 20%. The learned routes show
local models scoring 4.7 quality — below the 6.0 threshold
typically needed for reliable merges.
