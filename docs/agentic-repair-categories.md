# Agentic Repair — Failure Categories Reference

Quick reference for the failure categories handled by `runner/agentic_repair.py`.
Each category drives the repair contract injected into re-queued task prompts.

## Technical (auto-repairable)

These trigger an in-place repair directive preserving prior work:

| Category | Trigger | Typical fix |
|---|---|---|
| `buildfail` | Build/compile error | Fix syntax, imports, missing deps |
| `testfail` | Test suite failure | Fix test or implementation |
| `quality` | Lint / style gate | Auto-format or targeted fix |
| `verify` | Post-merge verification failure | Patch the verified artifact |
| `judge` | QA judge rejected the diff | Address review feedback |
| `noop` | No files changed | Ensure the task produces a commit |
| `missing-branch` | Expected branch not found | Reconstruct from artifacts |
| `conflict` | Merge conflict | Rebase and resolve |
| `timeout` | Execution exceeded time limit | Simplify or split the task |
| `runner-exception` | Unhandled runner error | Fix environment or fallback |
| `capacity` | Resource exhaustion | Retry after cooldown |
| `transient` | Temporary external failure | Simple retry |
| `orphaned-running` | Stale RUNNING state | Release and re-queue |
| `stale-merging` | Stuck in MERGING state | Release and re-queue |

## Non-technical

Categories outside this set (e.g. `rework`, `scope`) get a general repair
directive without the technical reproduction step.

## Replacement vs repair

`replacement_required()` returns `True` for categories where the entire
implementation should be redone rather than patched (currently: `rework`
and `scope`). All others attempt incremental repair on the existing branch.
