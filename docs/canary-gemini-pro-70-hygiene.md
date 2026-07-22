# Canary Gemini-Pro-70: Cross-Learning Route Documentation

## Purpose
This canary documents the cross-learning route selection mechanism observed
in the orchestration pipeline. Route quality scores (q) drive future coder
assignment based on historical outcome signals.

## Observed Routes
- pipeline_scout → local:llama3.2:3b (q=4.7)
- completion → local:llama3.2:3b (q=6.45)
- meta_loop_improvement → local:codestral:22b (q=7.7)
- build_fix → local:llama3.1 (q=7.7)

## No behavioral changes
This canary makes no code, dependency, or configuration changes.
