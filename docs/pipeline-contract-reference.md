# Pipeline Contract Reference

## Overview
Every task processed by the orchestrator carries a pipeline contract that
specifies the routing, preflight triage model, agentic coder, QA panel,
legal gate, and deploy-cost rules. This document captures the canonical
contract fields for reference.

## Key Fields
- **source**: origin of the task (e.g. `preflight-gate`, `operator-drop`, `loop`)
- **project**: target repository (beethoven, smarter, tomorrow, etc.)
- **task class**: categorization + risk level
- **preflight triage**: cheap model that screens for feasibility
- **strategy planner**: model that decomposes the task
- **agentic coder**: model/skill that writes the code
- **QA panel**: models that review the output
- **legal gate**: owner-only flag for sensitive changes
- **deploy-cost rule**: never push main/master directly; branch only

## Safety Invariants
1. Never run `vercel --prod` or equivalent from a task
2. Never push main/master/dev directly
3. Never delete or overwrite unrelated queued improvements
4. Reconcile with active loop-generated work
