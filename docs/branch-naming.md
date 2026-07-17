# Branch Naming Convention

All executor-produced branches follow the pattern `agent/{slug}`.
The slug is the task's unique identifier in the queue and maps
one-to-one with a database row.

## Rules

- Never push directly to `main`, `master`, or `dev`.
- Force-push is allowed on `agent/*` branches (executor owns them).
- After push, the merge train evaluates the branch for auto-merge.
- Branch names must be valid git refs (no spaces, no special chars
  beyond hyphens and alphanumerics).

## Cleanup

Stale agent branches are pruned periodically by the merge train
after a task reaches DONE or MERGED state.
