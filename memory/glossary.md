# Glossary — Claude Orchestrator

Workplace shorthand, project terms, acronyms, and internal language for the orchestrator project.

## Key Acronyms & Terms

| Term | Meaning | Context |
|------|---------|---------|
| **Orchestrator** | Claude Orchestrator v3 — distributed task executor + web dashboard | The project itself |
| **Runner** | Python script on your Mac that executes Claude Code and reports to Supabase | Runs continuously via launchd |
| **DAG** | Directed Acyclic Graph — contract-first task dependencies | `planner.py` generates DAGs |
| **Verify step** | Cheap-model review of diff before integration | `verify.py`; risky → approval card |
| **Approval card** | Review card shown on web dashboard (Why/Value/Risk) | For risky changes or self-improvements |
| **RLS** | Row Level Security — Supabase auth at database row level | Enforces who can see/edit what |
| **Service role** | Supabase service role (append-only permissions) | Only runner uses this; secrets in .env |
| **Anon key** | Supabase anonymous key (read public data) | Safe to expose; used by web dashboard |
| **UCB1** | Upper Confidence Bound algorithm (bandit learning) | Learns best model per workload |
| **Pgvector** | Postgres vector extension for semantic search | Embeds outcomes; finds similar solutions |
| **Worktree** | Git worktree (isolated branch/checkout) | Each task runs in its own worktree |
| **Integrate** | Merge code change to project's main branch | After verify passes, runner integrates |
| **Contract-first** | Task 1 defines shared types/API; all deps lock in | Prevents multi-project conflicts |
| **Self-review** | `eval_harness.py` proposes orchestrator improvements | Never self-edits; all changes via approval |
| **Cost burn-down** | Spending over time (dashboard chart) | Tracks Claude API spend |
| **Transient error** | Temporary failure (HTTP 409, network hiccup) | Treated as requeue, not terminal |

## Projects Registered in Orchestrator

| Codename | Full Project Name | Repo Path | Purpose |
|----------|-------------------|-----------|---------|
| **Tomorrow** | Tomorrow Warroom | `/Users/kpasch/Documents/tomorrow/tomorrow` | Legal workspace |
| **Smarter** | Smarter (AI Legal) | `/Users/kpasch/Documents/smarter` | AI-powered legal documents |
| **Apparently** | Apparently (Tech) | `/Users/kpasch/Documents/apparently` | Core tech + shared libs |

All three can run in parallel; orchestrator polls and respects per-project budgets.

## Multi-Account Setup

| Slot | Role | Status | Usage Model |
|------|------|--------|-------------|
| **Account 1** | Primary (main work) | Active | First choice; rotates when exhausted |
| **Account 2** | Secondary (high-volume overflow) | Standby | Activated when Account 1 exhausted |
| **Account 3** | Tertiary (research/batch jobs) | Standby | Activated when Account 1+2 exhausted |

Rotation: `account_pool.py` picks lowest-usage account when current exhausted. Always stays within Anthropic's usage policies.

## Supabase Schema (Quick Ref)

| Table | Key Fields | Notes |
|-------|-----------|-------|
| `projects` | id, name, repo_path, budget_cap | Register your repos here |
| `tasks` | id, prompt, project_id, status, deps | What orchestrator executes |
| `approvals` | id, task_id, diff, why, value, risk | Web dashboard approval queue |
| `outcomes` | id, task_id, cost, tokens, result | Immutable execution record |
| `accounts` | id, api_key_hash, usage_mtd, model_stats | Metadata per API account (rotation) |
| `runner_heartbeats` | runner_id, last_seen, status | Health monitoring |
| `knowledge` | id, embedding, outcome_id | pgvector semantic search |
| `budgets` | project_id, spend_cap_mtd | Monthly spend limits per project |
| `failures` | id, task_id, error_type, recovery | Learning from failures |

## File Locations & Secrets

**COMMITTED to git:**
- `web/` — Nuxt app (safe to commit)
- `supabase/migrations/` — Schema migrations
- `runner/` — Python code (safe to commit)
- `.gitignore` — Must include `*.env` and `runner/.env`
- `CLAUDE.md` — This project's dev guide
- `README.md`, `SETUP-PROMPT.md`, `DEPLOY.md`

**NEVER committed (git-ignored):**
- `runner/.env` — SUPABASE_SERVICE_KEY lives here only
- `web/.env.local` — Local dev secrets
- Any `.env*` file in any directory

## Development Commands (from /runner)

```bash
python3 runner.py                # Main loop: poll → claim → execute → verify → integrate
python3 runner.py --dry-run      # Test without committing
python3 runner.py --project-only tomorrow  # Filter to one project
python3 runner.py --replay-task <id>       # Retry a failed task
CLAUDE_BIN=claude python3 runner/planner.py "prompt"  # Generate task DAG
```

## How Orchestrator Auto-Switches (for Memory)

When Claude is invoked in this directory (`/Users/kpasch/Documents/beethoven/claude-orchestrator`):
1. Claude loads `/claude-orchestrator/CLAUDE.md` (hot cache)
2. Claude references this `memory/glossary.md` for full decoding
3. Claude switches account context automatically (via productivity memory)
4. Can decode shorthand: "queue a task for tomorrow" → understands it's the Tomorrow project

## Notes

- Orchestrator Supabase ref: `eatfwdzfurujcuwlhdgj` (live)
- Runner is intentionally on your Mac (not serverless) for: git creds, terminal access, Claude CLI auth, full control
- Web is thin client — all orchestration logic in runner + Supabase
- Cost tracking is per-account + per-project; budgets prevent runaway spend
