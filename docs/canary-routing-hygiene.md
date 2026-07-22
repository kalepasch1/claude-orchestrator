# Canary Routing Hygiene

Canary tasks validate that the coder-routing pipeline can claim, implement,
and push a minimal safe change end-to-end. They exist to catch regressions
in the executor → worktree → push → merge-train path without risking
production behavior.

## Guidelines

- Canary tasks must not change secrets, dependencies, billing, or legal copy.
- Acceptable canary changes: doc clarifications, comment improvements,
  dead-code removal, test hygiene, and trivial config tidying.
- Each canary commit must be independently mergeable and must not conflict
  with queued feature work.
- A canary that cannot find a safe improvement should commit this
  verification note rather than skipping.

## Verification

This document was committed by canary-ollama-2-63 to confirm the
beethoven executor pipeline is healthy.
