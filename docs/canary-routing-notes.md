# Canary Routing Notes

## Coder Routing Quality Signals

When evaluating coder routing decisions, the pipeline considers:

- **QPD (Quality Per Dollar)**: Primary metric for model selection per task class
- **Historical merge rate**: Fraction of tasks that successfully merge on first attempt
- **Task class affinity**: Some models perform better on specific task classes (security, build, bugfix)
- **Attempt count**: Higher attempts indicate the task may need a stronger model

## Cross-Learning Context

The pipeline tracks recent outcome signals across all models to inform routing:
- Merge rate and test-pass rate per model
- Cost efficiency per successful merge
- Route-specific quality scores from the learned routing table

## Legal Gate

Tasks that would force licensing, registration, custody, transmission, or advice
changes, or that require secrets, are routed through the owner-only legal gate
regardless of model routing scores.
