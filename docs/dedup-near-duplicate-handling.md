# Near-Duplicate Task Deduplication

Documents how the orchestration pipeline detects and handles
near-duplicate queued tasks to prevent redundant work.

## Detection

When a new task is queued, the pipeline checks for existing QUEUED
tasks with similar slugs or overlapping intent keywords. A similarity
score above the dedup threshold triggers consolidation.

## Handling

- **Primary task** — the earlier-queued task survives
- **Duplicate task** — marked with `dedup: near-duplicate queued task`
  and transitioned to a terminal state
- **Canary duplicates** — canaries that duplicate another canary are
  safe to rework since they measure coder routing, not feature delivery

## Recovery After Dedup

If a deduped task is later reworked (attempt > 0), the executor should:
1. Check if the primary task has already been completed
2. If completed, produce a distinct small improvement (not the same change)
3. If not completed, produce a complementary change that supports the primary
