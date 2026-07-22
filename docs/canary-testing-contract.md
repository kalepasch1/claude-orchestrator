# Canary Testing Contract

Canary tasks (`kind: canary`) validate that the executor pipeline can:

1. Claim a task from the queue via atomic CTE
2. Create an isolated worktree from the correct base branch
3. Fetch enrichment from `cowork_assemble.py` (graceful fallback on failure)
4. Commit and push to an `agent/{slug}` branch without touching the default branch
5. Mark the task DONE and heartbeat remaining claims

## Constraints

- Canary tasks must never change secrets, dependencies, billing, legal copy, or product behavior.
- The change must be safe to merge (doc, test hygiene, or trivial clarification only).
- Canary tasks validate coder routing: `force_coder` selects the AI vendor for the implementation step.

## Routing

The `force_coder` field on a canary task determines which AI backend implements it.
When `force_coder` is null, the executor uses its default (Claude via cowork session).
Named values (e.g., `xai`, `openai`, `gemini`) are resolved by runner.py's model router
but the cowork executor always uses Claude regardless — the field is informational for
pipeline telemetry and merge-train analysis.
