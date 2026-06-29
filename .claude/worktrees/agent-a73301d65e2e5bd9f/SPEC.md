# SPEC.md — Claude Orchestrator

> The orchestrator's `spec.py` compares this against the code weekly and
> files a reconciliation task when drift is detected.
> `planner.py` reads this before decomposing tasks so every generated
> sub-task satisfies these invariants automatically.

---

## Purpose

Autonomous multi-project build orchestrator: polls a task queue, decomposes features into sub-tasks, delegates to Claude Code agents, runs tests, gates deploys on confidence scores, records costs, and surfaces a live dashboard.

---

## Public API / Interface Contracts

### Task queue (Supabase `tasks` table)
- Required columns: `id uuid`, `project_id uuid`, `slug text`, `prompt text`, `state text`, `created_at timestamptz`
- Valid states: `QUEUED → RUNNING → DONE | FAILED | BLOCKED | MERGED`
- No direct `QUEUED → MERGED` transition
- `kind` = `feature | bugfix | refactor | batch | gtm` (open enum — new kinds allowed)

### Outcomes table
- Every completed task (DONE or MERGED) must have a corresponding `outcomes` row with `project`, `usd`, `tests_passed`, `integrated`

### REST endpoints (Nuxt server routes)
- `GET /api/health` → `200 { status: "ok" }`
- `POST /api/queue` body `{ project, slug, prompt }` → `201`
- `POST /api/nl-query` body `{ question }` → `200 { answer: string }`
- `POST /api/go-to-market` body `{ slug, target_project, product_name }` → `200 { ok, queued, project }`

### Edge functions (Supabase)
- `POST /functions/v1/ask` — NL analytics via Claude Haiku
- `POST /functions/v1/go-to-market` — launches GTM task with consent check

### Capability registry (`capability.py`)
- `publish()` always calls `privacy.scrub()` before writing; never persists raw PII
- `publish()` stores embedding in `capabilities.embedding` for pgvector dedup
- `version()` diffs contracts and files approval cards for breaking changes
- `instantiate()` checks `provenance.consent_ok()` before creating an instance

---

## Invariants

- All DB writes use upsert / `ON CONFLICT DO NOTHING` — no duplicate rows on retry
- RLS is enabled on every table; `SUPABASE_SERVICE_KEY` never reaches the browser
- `privacy.scrub()` is called on every path that writes user-supplied text to `capabilities`, `knowledge`, or `capability_versions`
- `provenance.record()` is called on every capability publish and instantiate
- `outcomes.usd` is recorded before a task transitions to DONE/MERGED
- Confidence gate (`confidence.py`) must clear before `pr_integrate` merges
- Embedding model changes require re-embedding all existing vectors (see `VOYAGE_EMBEDDING_MODEL` comment in `.env`)
- `CONTEXT_EMBED_PROVIDER` defaults to `EMBED_PROVIDER`; `context_embed` must not call the quality-path provider for bulk file ranking
- All launchd plists use `EnvironmentVariables` block — no env leaks through shell expansion at load time

---

## Out of Scope

- Multi-tenancy / SaaS billing — single-owner use only
- Real-time streaming task logs to the dashboard (polling is sufficient)
- Natural-language task creation via voice (text only)
- Capability marketplace / third-party publishing (closed registry, owner's projects only)
