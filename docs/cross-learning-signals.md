# Cross-Learning Signals

## Overview
The orchestrator tracks outcome signals from completed tasks and feeds
them back into routing decisions. This document describes the signal
format and how it influences model selection.

## Signal Format
Each completed task produces:
- **merge count**: N/total merged successfully
- **test-pass count**: N/total with green tests
- **cost**: USD spent on model inference
- **models used**: list of models that participated

## Learned Routes
The routing table maps task categories to preferred models based on
historical quality-per-dollar (QPD) scores:
- `pipeline_scout` → cheapest local model
- `completion` → local model with good completion quality
- `meta_loop_improvement` → local model with strong code reasoning
- `build_fix` → local model with debugging capability

## Operator Feedback
Human feedback is recorded per task with severity and category,
feeding into route calibration over time.
