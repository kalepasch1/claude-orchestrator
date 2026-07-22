# Orchestrator Account Setup Guide

This document explains how to set up and use the orchestrator as a third Claude account option, alongside your existing two accounts.

## Overview

You now have **3 Claude context options** that auto-switch:

| Account | Folder | Purpose | CLAUDE.md | Memory |
|---------|--------|---------|-----------|--------|
| 1 | `~/Documents/tomorrow/` | Legal workspace | ✅ | ✅ (if exists) |
| 2 | `~/Documents/smarter/` | AI legal docs | ✅ | ✅ (if exists) |
| **3 (NEW)** | **`~/Documents/beethoven/claude-orchestrator/`** | **Orchestrator control plane** | ✅ | **✅ (just created)** |

When you open Claude in any of these directories, it automatically loads the corresponding CLAUDE.md + memory system.

## What We Just Set Up

### 1. CLAUDE.md (Orchestrator Guide)
- **Location:** `/beethoven/claude-orchestrator/CLAUDE.md`
- **Content:** Tech stack (Nuxt 3 + Python + Supabase), commands, DO/DON'T rules
- **Auto-loads:** When you invoke Claude in this folder

### 2. Memory Structure
```
memory/
  glossary.md         ← Full decoder ring (terms, acronyms, accounts, projects)
  index.md            ← Quick reference
  README.md           ← How memory works
  projects/
    orchestrator.md   ← Detailed setup, debugging, commands
  context/
    account-pool.md   ← Multi-account rotation (3 accounts, monitoring)
```

### 3. Auto-Switching Logic
- When you invoke Claude in `/beethoven/claude-orchestrator/`, it:
  1. Loads `/beethoven/claude-orchestrator/CLAUDE.md` (hot cache)
  2. Can reference `/beethoven/claude-orchestrator/memory/` for full context
  3. Understands orchestrator-specific shorthand (DAG, runner, UCB1, etc.)
  4. Switches context automatically (like the other 2 account options)

## How to Use (Workflow)

### Scenario 1: Working on Orchestrator Web App
```bash
cd ~/Documents/beethoven/claude-orchestrator/web
# Claude loads orchestrator CLAUDE.md + memory
# Understands: Nuxt 3, Supabase, Tailwind, Vue 3
# Can help debug, refactor, deploy
```

### Scenario 2: Working on Orchestrator Runner
```bash
cd ~/Documents/beethoven/claude-orchestrator/runner
# Claude loads orchestrator CLAUDE.md + memory
# Understands: Python, account_pool.py, bandit.py, verify.py
# Can help write/debug task execution logic
```

### Scenario 3: Orchestrator Admin (Monitoring Tasks)
```bash
cd ~/Documents/beethoven/claude-orchestrator
# Claude loads full orchestrator context
# Can help you:
#   - Queue tasks for Tomorrow/Smarter/Apparently
#   - Approve risky changes from dashboard
#   - Monitor spend, debug failures
#   - Manage account rotation
```

### Scenario 4: Switching Back to Tomorrow/Smarter
```bash
cd ~/Documents/tomorrow/  # or ~/Documents/smarter/
# Claude auto-switches to that project's CLAUDE.md + memory
# Loses orchestrator context (intentional)
```

## Account Rotation (3 Accounts)

The orchestrator manages **3 authorized Anthropic accounts** automatically:

**runner/.env configuration:**
```bash
# Primary account
ANTHROPIC_API_KEY=sk-proj-your-primary-key

# Secondary account (when primary exhausted)
ACCOUNT_2_KEY=sk-proj-your-secondary-key

# Tertiary account (when 1+2 exhausted)
ACCOUNT_3_KEY=sk-proj-your-tertiary-key
```

**How rotation works:**
1. Runner starts with Account 1 (primary)
2. Monitors usage per account in Supabase `accounts` table
3. When Account 1 usage near limit → switches to Account 2
4. Bandit learning (UCB1) finds best model per workload after ~100 tasks
5. All rotations logged in `runner_heartbeats` for transparency

**Dashboard visibility:**
- "Spend" tab shows cost by account
- "Runner Health" shows account rotation status
- Budget caps per-project prevent runaway spend

## Configuration Files

### runner/.env (NEVER commit)
```bash
SUPABASE_URL=https://eatfwdzfurujcuwlhdgj.supabase.co
SUPABASE_SERVICE_KEY=sk-...     # SERVICE ROLE — SECRET
ANTHROPIC_API_KEY=sk-proj-...   # Account 1
ACCOUNT_2_KEY=sk-proj-...       # Account 2
ACCOUNT_3_KEY=sk-proj-...       # Account 3
MAX_PARALLEL=2
TEST_CMD="npm test"
```

### web/.env.local (local dev only)
```bash
SUPABASE_URL=https://eatfwdzfurujcuwlhdgj.supabase.co
SUPABASE_KEY=<anon-key>  # Public, safe to expose
```

### .gitignore (must include)
```
*.env
*.env.local
runner/.env
web/.env.local
node_modules/
.nuxt/
.output/
```

## Verification Checklist

- [ ] **CLAUDE.md created** — `/beethoven/claude-orchestrator/CLAUDE.md`
- [ ] **Memory structure built** — `memory/glossary.md`, `projects/`, `context/`
- [ ] **Runner .env configured** — 3 accounts set up in `runner/.env`
- [ ] **.gitignore updated** — `*.env` excluded
- [ ] **Web builds locally** — `cd web && npm run build` succeeds
- [ ] **Runner starts** — `cd runner && python3 runner.py` polls Supabase
- [ ] **Dashboard accessible** — Vercel URL loads, magic link sign-in works
- [ ] **Test task queued & executed** — runner claims → verify → integrate → dashboard updates
- [ ] **Account rotation tested** — check `runner_heartbeats` for rotation log

## Common Commands

```bash
# Start web dashboard (dev)
cd web && npm run dev

# Start runner (main loop)
cd runner && python3 runner.py

# Test without committing
python3 runner.py --dry-run --task-id <task-id>

# Generate task DAG
CLAUDE_BIN=claude python3 runner/planner.py "Build X end-to-end" > tasks.yaml

# Check Supabase
supabase sql "SELECT * FROM runner_heartbeats"
supabase sql "SELECT * FROM accounts"

# Deploy web to Vercel
cd web && npm run build && npx vercel --prod
```

## Switching Context (Account Options)

**To work on Tomorrow project:**
```bash
cd ~/Documents/tomorrow/
# Claude loads Tomorrow CLAUDE.md + its memory/
```

**To work on Smarter project:**
```bash
cd ~/Documents/smarter/
# Claude loads Smarter CLAUDE.md + its memory/
```

**To work on Orchestrator:**
```bash
cd ~/Documents/beethoven/claude-orchestrator/
# Claude loads Orchestrator CLAUDE.md + its memory/
```

## Next Steps

1. **Run `/productivity:start`** (if you have the skill) to sync this memory with your task lists
2. **Set up launchd** for the runner to run continuously (see `scripts/setup-scheduler.sh`)
3. **Configure budget caps** in Supabase `budgets` table per-project
4. **Monitor spend** weekly via dashboard
5. **Test account rotation** — confirm Account 2 kicks in when Account 1 exhausted

## Safety Reminders

- ✅ **DO** commit CLAUDE.md, memory/, .gitignore, code
- ✅ **DO** keep runner/.env git-ignored and safe
- ✅ **DO** monitor spend; set budget caps
- ✅ **DO** approve material changes before merge
- ✅ **DO** use authorized accounts only
- ❌ **DON'T** commit `.env` files
- ❌ **DON'T** share SUPABASE_SERVICE_KEY
- ❌ **DON'T** exhaust one account while others idle
- ❌ **DON'T** bypass approval gates for self-changes

---

**Questions?** Check `memory/glossary.md` (terms), `projects/orchestrator.md` (debugging), or `context/account-pool.md` (accounts).
