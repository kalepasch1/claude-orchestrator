# Canary Routing Glossary

Quick reference for coder-routing terminology used across the orchestrator.

| Term | Definition |
|------|-----------|
| **Canary task** | A lightweight probe task used to benchmark a coder route's reliability before production routing. |
| **Coder route** | A model+provider pair (e.g. `openai:gpt-4o-mini`) selected by the adaptive pipeline for a task class. |
| **QPD score** | Quality-per-dollar — the primary metric for comparing coder routes. Higher is better. |
| **Force coder** | Override that pins a task to a specific coder route, bypassing adaptive selection. |
| **Confidence gate** | Preflight check that estimates whether a task is well-scoped enough to produce a mergeable diff. |
| **Merge train** | Batch release process that promotes verified agent branches to the default branch. |
| **Zombie task** | A task stuck in RUNNING state because its executor session crashed or was rate-limited. |
| **Preflight directive** | Instruction appended when a cheap model predicts a task might not produce a concrete diff. |
