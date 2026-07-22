# Dedup Detection

## Problem
Multiple pipeline stages can emit near-identical tasks (same slug prefix,
overlapping acceptance criteria). Without dedup, the queue accumulates
redundant work that wastes executor cycles.

## Mechanism
Before a new task is inserted, the planner checks for existing QUEUED or
RUNNING tasks with the same slug prefix and project. If a near-duplicate
is found, the newer task is either merged into the existing one or
rejected with a `dedup: near-duplicate queued task` note.

## Edge Cases
- Canary tasks with different `force_coder` values are NOT duplicates
  even if their prompts are similar — each tests a distinct vendor path.
- Rework directives referencing a dedup failure should implement a
  unique doc or test change to avoid retriggering dedup on the next cycle.
