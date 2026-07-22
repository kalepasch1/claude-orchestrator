# Canary XAI-68: Pipeline Security Context

## Purpose
This canary documents the pipeline contract's security-class task handling,
confirming that the orchestration system correctly routes security-class tasks
through the legal gate when they would force licensing, registration, custody,
transmission, or advice — or when they require a secret.

## Observations
- The deploy-cost rule prevents direct production deploys via CLI.
- The coordination rule ensures reconciliation with active loop-generated work.
- Cross-learning context feeds back into route selection for future tasks.

## No behavioral changes
This canary makes no code, dependency, or configuration changes.
