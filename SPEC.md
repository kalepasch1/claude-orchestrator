# SPEC.md — Project Specification Template

> Copy this file into each managed repo as `SPEC.md` and fill it in.
> The orchestrator's `spec.py` compares this against the code weekly and
> files a reconciliation task when drift is detected.
> `planner.py` reads this before decomposing tasks so every generated
> sub-task satisfies these invariants automatically.

---

## Purpose

<!-- One sentence: what does this project do? -->

## Public API / Interface Contracts

<!-- Endpoints, function signatures, CLI flags, or schema that MUST remain stable. -->
<!-- Example:
- GET /api/health → 200 {"status":"ok"}
- POST /api/tasks body:{project_id, slug, prompt, kind} → 201
- DB table `tasks` always has columns: id, project_id, slug, prompt, state
-->

## Invariants

<!-- Rules that must always hold. These are the things spec.py checks. -->
<!-- Example:
- All DB writes are idempotent (ON CONFLICT DO NOTHING or upsert).
- No task transitions directly from QUEUED to MERGED (must pass RUNNING).
- RLS is enabled on every table; service-role key never reaches the frontend.
- All costs are recorded in `outcomes` before the task enters DONE/MERGED.
-->

## Out of Scope

<!-- What this project deliberately does NOT do (so planner doesn't add it). -->
