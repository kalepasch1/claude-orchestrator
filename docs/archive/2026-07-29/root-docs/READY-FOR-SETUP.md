# ✅ Ready for Setup — Next Actions

Your orchestrator is now **fully configured as a third Claude account option** with memory auto-switching. Here's what's ready and what you need to do next.

---

## What's Already Done ✅

### 1. Context System (Auto-Loads)
- ✅ `CLAUDE.md` — Orchestrator tech stack, commands, conventions
- ✅ `memory/glossary.md` — Terms, acronyms, 3 accounts, projects
- ✅ `memory/projects/orchestrator.md` — Architecture, debugging
- ✅ `memory/context/account-pool.md` — Multi-account rotation
- ✅ `TASKS.md` — Task tracking for orchestrator setup

**Result:** When you `cd ~/Documents/beethoven/claude-orchestrator/`, Claude automatically switches context and understands orchestrator-specific shorthand (DAG, runner, UCB1, verify step, etc.).

### 2. Account Setup (3-Account System)
- ✅ `ACCOUNT-SETUP.md` — Guide for integrating 3-account rotation
- ✅ `SETUP-CHECKLIST.md` — Step-by-step configuration instructions
- ✅ Memory files explain account rotation mechanics + monitoring

**Result:** Runner will auto-rotate across 3 authorized Anthropic accounts based on usage.

### 3. Documentation (Comprehensive)
- ✅ `README.md` — Overview of orchestrator architecture
- ✅ `SETUP-PROMPT.md` — Full deployment guide (6 phases)
- ✅ `DEPLOY.md`, `FEATURES.md` — Reference docs
- ✅ `memory/` — Rich context for Claude to work with

---

## What You Need to Do Now 🔄

### ACTION 1: Configure runner/.env (5 min)

You need **secrets only you have**:

```bash
cd ~/Documents/beethoven/claude-orchestrator/runner
cp .env.example .env
nano .env  # or your editor
```

**Add these (from your Supabase + Anthropic accounts):**
```bash
SUPABASE_URL=https://eatfwdzfurujcuwlhdgj.supabase.co
SUPABASE_SERVICE_KEY=<from Supabase Project Settings → API → service_role>

ANTHROPIC_API_KEY=sk-proj-<your-primary-account-key>
ACCOUNT_2_KEY=sk-proj-<your-secondary-account-key>    # optional
ACCOUNT_3_KEY=sk-proj-<your-tertiary-account-key>     # optional

MAX_PARALLEL=2
POLL_SECONDS=5
TEST_CMD="npm test"
```

**⚠️ CRITICAL:** This file contains secrets. Make sure:
- ✅ `.gitignore` includes `*.env` and `runner/.env`
- ✅ Run `git status` to confirm `.env` files are NOT tracked
- ✅ Never commit this file

### ACTION 2: Start Runner (2 min)

```bash
cd ~/Documents/beethoven/claude-orchestrator/runner

# Install Python deps (if not already installed)
pip3 install pyyaml

# Start runner (will poll Supabase every 5 sec)
set -a; . ./.env; set +a
python3 runner.py

# Should see output like:
# Connecting to Supabase...
# [✓] Connected
# Polling for tasks every 5 seconds...
# Waiting for tasks...
```

Keep this terminal open (or use `launchd` to run in background after testing).

### ACTION 3: Verify Runner is Online (1 min)

In another terminal:

```bash
# Check runner heartbeat
supabase sql "SELECT runner_id, status, last_seen FROM runner_heartbeats ORDER BY last_seen DESC LIMIT 1;"

# Should show:
# runner_id   | status | last_seen
# runner-mac  | online | 2026-07-07 12:34:56
```

### ACTION 4: Queue a Test Task (2 min)

**Via web dashboard (easiest):**
1. Go to Vercel URL from `SETUP-PROMPT.md` Phase 2
2. Sign in with magic link
3. Click "Queue Task"
4. Fill in:
   - **Project:** tomorrow
   - **Prompt:** `List the top 3 files by size in the repo (test)`
   - **Click:** Submit
5. Watch runner claim it (should appear in terminal as RUNNING)

**Via Supabase SQL (advanced):**
```sql
INSERT INTO tasks (id, project_id, prompt, status, created_at, kind)
VALUES (
  'test-1',
  'tomorrow',
  'List the top 3 files by size (test)',
  'pending',
  NOW(),
  'verification'
);
```

### ACTION 5: Monitor Execution (1 min)

In runner terminal, you should see:
```
[✓] Claimed task: test-1
[→] RUNNING: List the top 3 files...
[→] Created worktree...
[→] Executing: CLAUDE_BIN=claude python3 runner.py [prompt]
...
[✓] Verify step passed
[✓] Integrated: committed + pushed
[✓] Recorded outcome: cost=$0.015, tokens=120
```

In web dashboard:
- "Tasks" tab → task shows COMPLETED
- "Spend" tab → new row with cost/tokens
- "Runner Health" → heartbeat fresh

### ACTION 6: Set Budget Caps (2 min)

Prevent runaway spend:

```sql
-- Set monthly budget caps per project
INSERT INTO budgets (project_id, spend_cap_mtd) VALUES ('tomorrow', 10.00);
INSERT INTO budgets (project_id, spend_cap_mtd) VALUES ('smarter', 25.00);
INSERT INTO budgets (project_id, spend_cap_mtd) VALUES ('apparently', 15.00);

-- View budgets
SELECT * FROM budgets;
```

When a project exceeds its cap, runner rejects new tasks + creates approval card.

---

## Expected Timeline

| Step | Time | Status |
|------|------|--------|
| ACTION 1: Configure runner/.env | 5 min | Ready now |
| ACTION 2: Start runner | 2 min | Ready now |
| ACTION 3: Verify heartbeat | 1 min | Ready now |
| ACTION 4: Queue test task | 2 min | Ready now |
| ACTION 5: Monitor execution | 1 min | Ready now |
| ACTION 6: Set budget caps | 2 min | Ready now |
| **Total End-to-End Test** | **~13 min** | **Ready now** |

---

## What's Automatic After Setup ✅

Once runner is configured and running:

1. **Auto-Switching Context:**
   - `cd ~/Documents/beethoven/claude-orchestrator/` → Claude loads orchestrator CLAUDE.md + memory
   - `cd ~/Documents/tomorrow/` → Claude switches to Tomorrow context
   - `cd ~/Documents/smarter/` → Claude switches to Smarter context

2. **Auto-Rotating Accounts:**
   - Runner starts with Account 1 (primary)
   - When Account 1 usage nears limit → automatically switches to Account 2
   - All rotations logged in `runner_heartbeats` table
   - No manual intervention needed

3. **Auto-Learning (Bandit Learning):**
   - After ~100 tasks, runner learns best model per workload type
   - UCB1 (Upper Confidence Bound) balances cost vs. throughput
   - Dashboard shows model choice + spend impact

4. **Auto-Monitoring:**
   - Dashboard updates live (Supabase subscriptions)
   - Cost + tokens tracked per task
   - Budget caps enforced
   - Spend burn-down chart

5. **Auto-Learning Knowledge:**
   - Every outcome embedded in pgvector
   - New tasks search similar solutions (faster, cheaper)
   - Cross-project learning (Tomorrow solutions help Smarter/Apparently)

---

## Important Reminders ⚠️

### Secrets
- ✅ Keep `runner/.env` git-ignored
- ✅ Never commit SUPABASE_SERVICE_KEY or ANTHROPIC_API_KEY
- ✅ Regenerate keys if leaked

### Account Rotation
- ✅ Only rotate accounts you're authorized to use
- ✅ Respect Anthropic's usage policies
- ✅ Monitor spend weekly via dashboard

### Approval Gates
- ✅ Risky diffs require your approval before merging
- ✅ Self-changes go through git + CI + your review (never silent)
- ✅ All Claude calls are logged (audit trail)

### Multi-Project Safety
- ✅ Contract-first DAGs prevent conflicts (task 1 = shared types)
- ✅ Per-project budgets prevent runaway spend
- ✅ Verify step reviews changes before integration

---

## Files You Now Have

### Configuration
- `CLAUDE.md` — Tech stack + conventions
- `runner/.env.example` — Template (you copy → configure)
- `web/.env.example` — Template (already in git)

### Memory (Auto-Loads)
- `memory/glossary.md` — Decoder ring (50+ terms)
- `memory/projects/orchestrator.md` — Architecture + commands
- `memory/context/account-pool.md` — Account rotation system
- `memory/index.md` — Quick reference
- `memory/README.md` — Memory structure

### Guidance
- `ACCOUNT-SETUP.md` — Integration guide (3 accounts)
- `SETUP-CHECKLIST.md` — Step-by-step instructions
- `SETUP-PROMPT.md` — Full deployment (6 phases)
- `TASKS.md` — Task tracking

### Code
- `runner/` — Python orchestrator (runner.py, account_pool.py, etc.)
- `web/` — Nuxt dashboard (deployed to Vercel)
- `supabase/` — Migrations + RLS policies + edge functions

---

## Next: Make It Durable (Optional)

After verifying end-to-end, make runner always-on:

```bash
# Install launchd plist (runs on startup)
bash scripts/setup-scheduler.sh

# This creates:
# - Runner plist (KeepAlive=true)
# - Nightly self-review
# - Hourly anomaly detection
# - 2-5 AM research window
```

Runner will then restart automatically if your Mac reboots.

---

## Questions?

- **"What does UCB1 mean?"** → Check `memory/glossary.md`
- **"How do I debug a task?"** → Check `memory/projects/orchestrator.md` → Debugging section
- **"How do I add a 4th account?"** → Check `memory/context/account-pool.md` → Troubleshooting
- **"What's the spend limit?"** → Set in `budgets` table (per-project)

---

## Summary

✅ **READY:** Memory system + context switching + 3-account setup  
🔄 **NEXT:** Configure runner/.env, start runner, queue test task  
📊 **RESULT:** Orchestrator controlling all 3 projects (Tomorrow, Smarter, Apparently) with automatic account rotation

**Time to first working end-to-end test:** ~13 minutes

Go to ACTION 1 above and let's get it live. 🚀
