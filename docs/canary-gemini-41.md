# Canary: Coder Routing Recovery Test (Gemini)

## Purpose
Validates that the Gemini coder path can reconstruct missing-branch
work using reuse-first context from the recovery pipeline.

## Test Scope
- Single tiny safe change with no behavioral impact
- No modifications to secrets, dependencies, or package managers
- Preserves existing behavior and acceptance criteria

## Recovery Pipeline Context
The orchestrator tracks missing agent branches via merge train pressure
metrics. When a branch is detected as stale or missing, the recovery
system attempts zero-spend reconstruction from cached templates and
patch transplant hints before falling back to full regeneration.

## Result
Canary committed successfully — routing validation complete.
