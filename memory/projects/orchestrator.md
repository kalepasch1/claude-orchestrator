# Project: Claude Orchestrator

**Also known as:** Orchestrator, Orchestrator v3, "the orchestrator"
**Location:** `/Users/kpasch/Documents/beethoven/claude-orchestrator`
**Status:** Active — multi-project distributed task executor
**Deployed:** Web on Vercel, Runner on local Mac, Supabase backend live

## What It Is

A **shareable hosted control plane** for executing Claude Code across all your projects (Tomorrow, Smarter, Apparently) with:
- **Web dashboard** (Nuxt + Tailwind on Vercel): queue tasks, approve changes, view spend
- **Python runner** (on your Mac): polls Supabase, executes Claude Code in git worktrees, learns model routing
- **Supabase backend** (PostgreSQL + pgvector): stores tasks, outcomes, approvals, knowledge embeddings
- **Multi-account rotation**: cycles through authorized Anthropic accounts based on usage
- **Self-improvement loop**: `eval_harness.py` proposes orchestrator improvements (with approval)

## Why This Architecture

- **Runner on Mac:** Needs terminal, git creds, Claude CLI auth, full file system access — can't run serverless
- **Web on Vercel:** Thin client for dashboard, real-time updates, member collaboration
- **Supabase central:** Single source of truth for tasks, outcomes, approvals, cost tracking

## Key People / Roles

| Who | Role | Contact |
|-----|------|---------|
| **Macey** (you) | Orchestrator admin + developer | kale@smrter.us |

## Current Setup Status

- ✅ Supabase project live (ref: `eatfwdzfurujcuwlhdgj`)
- ✅ Web deployed to Vercel (link: check `SETUP-PROMPT.md` Phase 2)
- ✅ Runner installed locally (Python 3.11+)
- ⏳ Runner launchd scheduler (setup via `scripts/setup-scheduler.sh`)
- ⏳ Slack edge functions (optional, in `supabase/functions/`)

## Registered Projects

The orchestrator can manage these repos in parallel:

1. **Tomorrow** — Legal workspace + warroom
2. **Smarter** — AI legal assistant (Nuxt)
3. **Apparently** — Core tech stack + shared libs (Nuxt 4)

Each has a row in `supabase.projects` table with budget caps and model preferences.

## How It Works: Task Execution

```
1. Queue task from web dashboard (or push to API)
   └─ Specify: prompt + project + dependencies
2. Runner polls Supabase every 5 sec, claims task → RUNNING
3. Runner creates git worktree for project
4. Executes: CLAUDE_BIN=claude python3 runner.py [prompt]
   └─ Claude Code runs in isolation (no side effects elsewhere)
5. Verify step: `verify.py` cheap-model reviews diff
   └─ Safe → integrate (commit + push to project's main)
   └─ Risky → approval card on dashboard (for you to review)
6. Outcome recorded: cost ($), tokens, status
7. Dashboard updates live (Supabase subscriptions)
```

## Multi-Account Rotation

- **account_pool.py** cycles through your authorized Anthropic accounts
- Picks lowest-usage account when current one exhausted
- Falls back to model heuristics (cost/throughput) when cold; UCB1 bandit learns after ~100 runs
- ⚠️ **Safety:** Only rotate accounts you're entitled to; respect Anthropic's usage policies

**Current setup:** 3 accounts registered (1 primary, 2 standby)

## Knowledge Reuse & Learning

- **pgvector embeddings:** `knowledge.py` embeds every task outcome
- New task → semantic search finds similar past solutions → faster, cheaper
- Cached context prefix (16k-32k stable tokens) reduces input cost
- Cross-project learning: solutions from Tomorrow can help Smarter & Apparently

## Self-Improvement (Safety-Gated)

- **eval_harness.py** analyzes telemetry (spend, failures, token patterns)
- Proposes improvements to orchestrator itself as **approval cards**
- Never self-edits silently — all material changes:
  1. Proposed as branch/PR
  2. Tested in CI
  3. Require your approval before merge
  4. A/B gated before rollout

## Environment & Secrets

**Web (.env.local for dev, Vercel env for prod):**
```bash
SUPABASE_URL=https://eatfwdzfurujcuwlhdgj.supabase.co
SUPABASE_KEY=<anon-key>  # Public, safe to expose
```

**Runner (.env, NEVER commit):**
```bash
SUPABASE_URL=https://eatfwdzfurujcuwlhdgj.supabase.co
SUPABASE_SERVICE_KEY=<service-role-key>  # SECRET
ANTHROPIC_API_KEY=sk-...  # Primary account
MAX_PARALLEL=2
TEST_CMD="npm test"
```

## Key Commands

| Command | Purpose |
|---------|---------|
| `cd web && npm run dev` | Start web dashboard locally |
| `cd web && npm run build` | Build for production (Vercel) |
| `cd runner && python3 runner.py` | Start main loop (polls Supabase) |
| `python3 runner.py --dry-run --task-id <id>` | Test task without committing |
| `CLAUDE_BIN=claude python3 runner/planner.py "Build X"` | Generate contract-first DAG |
| `supabase db push` | Apply migrations to Supabase |
| `supabase functions deploy` | Deploy Slack edge functions (optional) |

## Deployment Checklist

- [ ] Supabase migrations applied
- [ ] Web built + deployed to Vercel (env vars set)
- [ ] Runner: Python deps installed, `.env` configured, launchd plist created
- [ ] E2E test: queue task → runner claims → verify → integrate → dashboard updates
- [ ] Secrets audit: no `.env` files in git; `git log -p | grep -i service_role` returns nothing
- [ ] Budget caps set per-project in `budgets` table
- [ ] Slack functions deployed (optional)

## Common Tasks

**Queue a task:**
- Go to deployed web dashboard → "Queue Task"
- Paste prompt, select project, add dependencies
- Submit → runner polls and claims

**Approve a risky change:**
- Check web dashboard "Approvals" tab
- Review Why/Value/Risk
- Click Approve → runner integrates

**Monitor spend:**
- Dashboard "Spend" tab shows burn-down chart
- Per-project budgets prevent overruns
- View account rotation in `runner_heartbeats` table

**Debug a failed task:**
- Check task status + error log on dashboard
- `supabase sql "SELECT * FROM outcomes WHERE task_id = '...'"` for details
- Replay: `python3 runner.py --replay-task <id>`

## Notes

- Runner is intentionally local (not serverless) — needs terminal, git creds, Claude CLI auth
- All changes before merge require approval (no silent self-edits)
- Cost tracking per-account + per-project; budgets are enforced
- Knowledge embeddings are permanent (don't delete `knowledge` table rows)
- Multi-project DAGs lock contracts early (prevents conflicts)
