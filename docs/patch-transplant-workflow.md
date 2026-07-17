# Patch Transplant Workflow

Describes how the executor reuses proven patches from other projects
to accelerate task completion.

## Transplant Sources

The `PATCH TRANSPLANT` directive in a task prompt references a prior
successful patch from another project. The executor should:

1. Read the transplant source diff (if available in the prompt)
2. Identify the analogous files in the current project
3. Adapt — not copy — the proven pattern to the local codebase
4. Preserve existing behavior (acceptance criterion)

## Similarity Scores

- **> 0.7** — high confidence transplant; apply with minimal adaptation
- **0.4–0.7** — moderate; adapt the approach but verify carefully
- **< 0.4** — low; use as inspiration only, draft from scratch

## Common Failure Modes

- Transplanting a patch verbatim without adapting file paths
- Ignoring project-specific conventions (e.g., ESM vs CJS)
- Missing acceptance criteria in the original task
