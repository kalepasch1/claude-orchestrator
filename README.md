# Claude Orchestrator — Cloud (v3)

A **shareable hosted control plane** (Nuxt + Supabase + Tailwind on Vercel) plus a
**Mac runner** that executes Claude Code across all your projects, learns from its own
results, and only stops for the material changes you approve. Built on the tested v2
runner logic, now backed by Supabase so you and your partners watch and approve from
anywhere.

```
┌────────────────────────┐        ┌──────────────────────┐        ┌────────────────────┐
│  Web (Vercel)          │  realtime │  Supabase           │  REST  │  Runner (your Mac) │
│  Nuxt + Tailwind       │◄────────►│  tasks / approvals  │◄──────►│  executes Claude    │
│  monitor + approve      │  auth    │  outcomes / cost    │ service│  Code in worktrees  │
│  partners log in        │          │  knowledge (pgvec)  │  key   │  reports status/$   │
└────────────────────────┘        └──────────────────────┘        └────────────────────┘
```
Why split: a website can't run 60-turn Claude Code builds, hold git worktrees, or use
your CLI login. So the **runner** does execution where your code lives; the **website**
is the shared dashboard. (Move the runner to an always-on cloud VM later — same code.)

## Setup (about 15 min)

**1. Supabase** — create a project, then run the migration:
```
supabase link --project-ref YOUR-REF
supabase db push          # applies supabase/migrations/0001_init.sql
```
Enable Email auth (magic links) in Supabase → Authentication. Add your + partners' emails.

**2. Web (Vercel)** — deploy `web/`:
```
cd web && npm install
# set env: SUPABASE_URL, SUPABASE_KEY (anon)  — locally in .env, and in Vercel project settings
npm run dev          # or: vercel  (import the repo in Vercel, root = web/)
```
Open the URL → sign in with a magic link → you'll see the dashboard.

**3. Runner (your Mac)**:
```
cd runner && cp .env.example .env   # fill SUPABASE_URL + SUPABASE_SERVICE_KEY (service key, Mac only)
pip3 install pyyaml
set -a; . ./.env; set +a
python3 runner.py        # polls Supabase, runs queued tasks, reports back
```
Register a project (one row in `projects`: name + absolute `repo_path`). Queue tasks
from the dashboard, or generate a DAG from a master prompt:
```
CLAUDE_BIN=claude python3 runner/planner.py "Build X end to end" > tasks.yaml   # contract-first DAG
```

## What's inside

**Runner (`runner/`)**
- `runner.py` — poll → claim → isolate (worktree) → run Claude Code → **verify** →
  integrate → report `outcomes` + cost to Supabase. Honors task `deps`.
- `bandit.py` — learns model choice from `outcomes` (UCB1, throughput-per-dollar);
  falls back to `model_router.py` heuristics when cold.
- `account_pool.py` — rotates among **your authorized** accounts on usage-exhaustion.
  ⚠️ Only use accounts you're entitled to; stay within Anthropic's usage policies.
- `caching.py` — stable cached context prefix (big input-token savings).
- `knowledge_embed.py` — semantic cross-project reuse via Supabase **pgvector**
  (keyword fallback if no embed key). `planner.py` is **contract-first** (shared
  types/API as task 1, everything depends on it → branches can't structurally conflict).
- `verify.py` — cheap-model reviews the diff **before** integrate; fail → approval card.
- `self_review.py` + `eval_harness.py` — the **self-improving loop**: reads its own
  telemetry, proposes orchestrator improvements as approval cards, and A/B-gates prompt
  changes before adoption. Never self-edits silently; material self-changes go through
  git + CI + your approval.

**Web (`web/`)** — Nuxt + Tailwind dashboard: realtime tasks board, approval queue with
**Why / Value / Risk / Alternatives**, queue-a-task form, spend-by-model, runner health.

**Supabase (`supabase/`)** — schema, RLS (members read/act, runner uses service role),
realtime, pgvector + `match_knowledge()`.

## Scheduling (continuous + windows)
Run the runner under launchd (always on). For the 2–5 AM research window and overnight
deploys with canary/rollback, reuse the v2 `scripts/` (`run-research.sh`,
`deploy-window.sh`, `setup-scheduler.sh`) pointed at this runner, or add Supabase cron
jobs that insert `research`/`efficiency` tasks on a schedule.

## Self-improvement, safely
The meta-loop improves the orchestrator itself — but every self-change is a *proposal*
you approve, applied on a branch through CI, gated by `eval_harness.py`, and revertible.
This is the explicit guard against the runaway self-loop that produced the 24-file
conflict pile-up in your earlier sessions.

## Roadmap still open
Supabase **cron** for fully-hosted scheduling; per-partner roles/permissions; live cost
charts (Chart.js); auto-extract knowledge after every task; move the runner to a cloud
VM for 24/7 independence.

This project utilizes the internal 'beethoven' build framework.
