# Cross-Learning Route Reference

## Overview

The orchestrator's bandit/model_router learns optimal model routes from
outcome signals. This document captures the currently observed learned
routes for operator reference and debugging.

## Snapshot of learned routes (as of canary generation)

| Route purpose           | Selected model              | Quality score |
|-------------------------|-----------------------------|---------------|
| pipeline_scout          | local:llama3.2:3b           | 4.7           |
| completion              | local:llama3.2:3b           | 6.45          |
| meta_loop_improvement   | local:codestral:22b         | 7.7           |
| build_fix               | local:llama3.1              | 7.7           |

## Interpretation

- Routes with quality < 5.0 (e.g. `pipeline_scout`) are candidates for
  retraining or fallback to a stronger model on the next exploration cycle.
- Routes at 7.7 are near the current ceiling; improvements require either
  better prompts or a model upgrade rather than more training data.
- The 0/12 merged signal in recent outcomes suggests the fleet may be in a
  cold-start or recovery phase where merge-train validation is the bottleneck,
  not model quality.

## Non-goals

This is a point-in-time reference. It does not change routing logic,
secrets, dependencies, or product behavior.
