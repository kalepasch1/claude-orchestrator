# Canary Routing Notes

## Purpose
Documents the coder-routing canary system used by the orchestrator
to validate that each AI vendor pathway (xai, claude, gpt, ollama, gemini, deepseek)
can successfully claim, implement, commit, and push a task branch.

## How Canaries Work
1. `planner.py` emits canary tasks with `force_coder` set to each vendor.
2. The executor claims and implements a tiny, safe change (doc, test hygiene, comment).
3. Success/failure feeds back into the QPD (quality-per-dollar) routing table.

## Acceptance Criteria
- No secrets, dependency changes, or product behavior changes.
- Must merge cleanly against the default base branch.
- One minimal file change (doc clarification, comment, or test improvement).
