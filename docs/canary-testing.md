# Canary Task Pattern

Canary tasks validate that the coder-routing pipeline can claim, implement,
commit, and push a minimal change end-to-end. They are generated from
historical merged-task metadata and intentionally scoped to zero-risk
changes such as documentation clarifications or comment hygiene.

## Acceptance criteria

- The change must not alter secrets, dependencies, billing, legal copy,
  or product behaviour.
- The commit must merge cleanly against the default branch.
- The task must complete within the executor's normal timeout window.

## When canary tasks are created

The orchestrator emits canary tasks when a coder route has no recent
successful merge signal. A passing canary restores confidence in that
route without risking a production-grade change.
