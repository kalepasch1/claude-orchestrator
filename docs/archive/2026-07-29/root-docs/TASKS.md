# Orchestrator Tasks

## Completed ✅

- [x] Create CLAUDE.md with orchestrator tech stack & conventions
- [x] Set up memory system (glossary.md, projects/, context/)
- [x] Create ACCOUNT-SETUP.md integration guide
- [x] Register orchestrator as 3rd Claude account option

## In Progress 🔄

- [ ] Configure runner/.env with 3 API keys
- [ ] Run `/productivity:start` to sync memory with task lists
- [ ] Test: Queue a task → confirm runner picks it up
- [ ] Monitor: Set budget caps per-project in Supabase

## Pending 📋

### Phase 1: Runner Setup (Critical)
- [ ] Copy `.env.example` to `runner/.env`
- [ ] Fill in SUPABASE_URL and SUPABASE_SERVICE_KEY
- [ ] Add ANTHROPIC_API_KEY (Account 1)
- [ ] (Optional) Add ACCOUNT_2_KEY and ACCOUNT_3_KEY for fallback rotation
- [ ] Test: `python3 runner.py --dry-run` on a test task
- [ ] Verify runner shows up in Supabase `runner_heartbeats` table

### Phase 2: Web Dashboard (Admin)
- [ ] Confirm web builds locally: `cd web && npm run build`
- [ ] Verify Vercel deployment from SETUP-PROMPT.md Phase 2
- [ ] Test sign-in with magic link (Supabase email auth)
- [ ] Check seeded tasks, approvals, spend chart render

### Phase 3: Multi-Project Integration
- [ ] Verify Tomorrow project registered in `projects` table
- [ ] Verify Smarter project registered in `projects` table
- [ ] Verify Apparently project registered in `projects` table
- [ ] Set budget caps in `budgets` table per-project

### Phase 4: Account Rotation Testing
- [ ] Queue a task from web dashboard
- [ ] Confirm runner claims it (check `tasks` status → RUNNING)
- [ ] Verify execution: diff review → verify step
- [ ] Confirm outcome recorded in `outcomes` table (cost, tokens)
- [ ] Check `runner_heartbeats` for account rotation log
- [ ] Simulate Account 1 exhaustion → confirm Account 2 activates

### Phase 5: Knowledge & Learning (Optional)
- [ ] Set up pgvector embeddings (EMBED_PROVIDER in .env)
- [ ] Test knowledge reuse: embed prior outcomes, semantic search
- [ ] Enable eval_harness.py for self-improvement proposals

### Phase 6: Scheduling & Durability
- [ ] Create launchd plist for runner (runs on startup)
- [ ] Set up nightly `self_review.py`
- [ ] Set up hourly `anomaly.py` (cost/error detection)
- [ ] Test: restart Mac → runner comes back up automatically

### Phase 7: Slack Integration (Optional)
- [ ] Deploy Supabase edge functions (`supabase functions deploy`)
- [ ] Create Slack app + webhook
- [ ] Set SLACK_WEBHOOK in runner/.env
- [ ] Test: approval card → Slack notification

## Blocked / Waiting
- [ ] Waiting for SUPABASE_SERVICE_KEY (only you have this)
- [ ] Waiting for 3 ANTHROPIC_API_KEY values (your accounts)

## Notes

**Key Files:**
- `CLAUDE.md` — Orchestrator tech guide (auto-loads)
- `ACCOUNT-SETUP.md` — 3-account integration workflow
- `runner/.env` — Configuration (SECRET — never commit)
- `web/.env.local` — Local dev secrets (never commit)

**Dashboard:**
- Deployed to Vercel (check SETUP-PROMPT.md Phase 2 for URL)
- Real-time task board + approvals queue + spend chart
- Magic link sign-in via Supabase email auth

**Runner:**
- Runs on your Mac (not serverless — needs terminal, git, Claude CLI)
- Polls Supabase every 5 seconds
- Auto-rotates across 3 accounts (Account 1 → 2 → 3)
- Logs all executions to `outcomes` table (immutable audit trail)

**Memory System:**
- `memory/glossary.md` — All terms, acronyms, projects, accounts
- `memory/projects/orchestrator.md` — Setup, debugging, commands
- `memory/context/account-pool.md` — Account rotation mechanics
- Auto-loads when working in this folder

**Next Step:** Configure `runner/.env` with your API keys + Supabase credentials.
