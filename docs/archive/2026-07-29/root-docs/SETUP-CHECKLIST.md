# Setup Checklist — Claude Orchestrator

Status: **Memory & context system complete** ✅  
Next: **Configure secrets & test end-to-end** 🔄

---

## Quick Start (TL;DR)

```bash
# 1. Configure runner (requires your secrets)
cd ~/Documents/beethoven/claude-orchestrator/runner
cp .env.example .env
# Edit .env: add SUPABASE_SERVICE_KEY, 3 x ANTHROPIC_API_KEY

# 2. Install Python deps
pip3 install pyyaml

# 3. Start runner
set -a; . ./.env; set +a
python3 runner.py

# 4. Open web dashboard (deployed to Vercel)
# Check SETUP-PROMPT.md Phase 2 for URL

# 5. From dashboard: Queue a test task → confirm runner claims it
```

---

## Step 1: Configure runner/.env

### What You Need

From Supabase (https://app.supabase.com/projects):
- **SUPABASE_URL** — project URL (safe to commit)
- **SUPABASE_SERVICE_KEY** — service role key (SECRET — .env only)

From Anthropic console (https://console.anthropic.com):
- **ANTHROPIC_API_KEY** — Account 1 (primary)
- **ACCOUNT_2_KEY** — Account 2 (optional, for rotation)
- **ACCOUNT_3_KEY** — Account 3 (optional, for rotation)

### How to Configure

```bash
cd ~/Documents/beethoven/claude-orchestrator/runner
cp .env.example .env
nano .env    # or your editor
```

**Minimal setup (Account 1 only):**
```bash
SUPABASE_URL=https://eatfwdzfurujcuwlhdgj.supabase.co
SUPABASE_SERVICE_KEY=<your-service-role-key>
ANTHROPIC_API_KEY=sk-proj-your-primary-account-key
MAX_PARALLEL=2
POLL_SECONDS=5
TEST_CMD="npm test"
```

**Full setup (3 accounts for rotation):**
```bash
SUPABASE_URL=https://eatfwdzfurujcuwlhdgj.supabase.co
SUPABASE_SERVICE_KEY=<your-service-role-key>

ANTHROPIC_API_KEY=sk-proj-your-primary-account-key
ACCOUNT_2_KEY=sk-proj-your-secondary-account-key
ACCOUNT_3_KEY=sk-proj-your-tertiary-account-key

MAX_PARALLEL=2
POLL_SECONDS=5
TEST_CMD="npm test"
```

### Verify Configuration

```bash
# Test Supabase connection
python3 -c "
from supabase import create_client
import os
url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_SERVICE_KEY')
client = create_client(url, key)
projects = client.table('projects').select('*').execute()
print(f'✅ Connected. Found {len(projects.data)} projects.')
"

# Test Anthropic API key
python3 -c "
from anthropic import Anthropic
import os
key = os.getenv('ANTHROPIC_API_KEY')
client = Anthropic(api_key=key)
# (Don't actually call the API; just verify the client initializes)
print('✅ API key accepted.')
"
```

---

## Step 2: Sync Memory with /productivity:start

The productivity system is already initialized with:
- ✅ `CLAUDE.md` (tech stack, conventions)
- ✅ `memory/glossary.md` (terms, acronyms, accounts, projects)
- ✅ `memory/projects/orchestrator.md` (detailed setup)
- ✅ `memory/context/account-pool.md` (account rotation)
- ✅ `TASKS.md` (task list)

**To update memory after changes:**
```bash
# From orchestrator folder
/productivity:update
# or for deep scan
/productivity:update --comprehensive
```

Memory is already synced with the 3-account setup. When you work in this folder, Claude automatically understands:
- 3 accounts (primary + 2 standby)
- Account rotation (UCB1 bandit learning)
- Registered projects (Tomorrow, Smarter, Apparently)

---

## Step 3: Test End-to-End (Queue → Execute → Verify)

### Test Task 1: Verify Runner Heartbeat

```bash
# Start runner in one terminal
cd ~/Documents/beethoven/claude-orchestrator/runner
python3 runner.py

# In another terminal, check it registered
supabase sql "SELECT runner_id, status, last_seen FROM runner_heartbeats ORDER BY last_seen DESC LIMIT 1;"
# Should show: runner online, heartbeat fresh
```

### Test Task 2: Queue a Dry-Run Task

**Via Supabase (raw SQL):**
```sql
INSERT INTO tasks (
  id, project_id, prompt, status, created_at, kind
) VALUES (
  'test-dry-run-1',
  'tomorrow',
  'List the top 3 files by size in the repo (dry run)',
  'pending',
  NOW(),
  'verification'
);
```

**Via dashboard (web):**
1. Go to deployed Vercel URL (from SETUP-PROMPT.md Phase 2)
2. Sign in with magic link
3. Click "Queue Task"
4. Fill in:
   - Project: **tomorrow**
   - Prompt: **List the top 3 files by size (test dry run)**
   - Submit

### Test Task 3: Watch Runner Execute

In runner terminal:
```
Polling Supabase... (every 5 sec)
[✓] Claimed task-id: test-dry-run-1
[→] RUNNING: List the top 3 files...
[→] Created worktree: /tmp/tomorrow-worktree-abc123
[→] Executing: CLAUDE_BIN=claude python3 runner.py [prompt]
...
[✓] Verify step passed (diff reviewed by cheap model)
[✓] Integrated: git commit + push to main
[✓] Recorded outcome: cost=$0.015, tokens=120, status=success
```

### Test Task 4: Check Dashboard

In browser (Vercel URL):
- "Tasks" tab → **test-dry-run-1** shows status: COMPLETED
- "Spend" tab → new row for this task (cost, tokens, model)
- "Runner Health" → heartbeat fresh, account rotation logged

### Test Task 5: Verify Supabase Tables

```bash
# Check task status
supabase sql "SELECT * FROM tasks WHERE id = 'test-dry-run-1';"
# Status should be: success

# Check outcome (cost, tokens)
supabase sql "SELECT * FROM outcomes WHERE task_id = 'test-dry-run-1';"
# Should show: cost, tokens, model used, execution time

# Check accounts table (rotation, usage)
supabase sql "SELECT id, usage_mtd, model_stats FROM accounts;"
```

---

## Step 4: Set Budget Caps (Cost Control)

Budget caps prevent runaway spend. Set per-project:

```sql
-- Set $10/month budget for Tomorrow
INSERT INTO budgets (project_id, spend_cap_mtd) VALUES ('tomorrow', 10.00)
ON CONFLICT (project_id) DO UPDATE SET spend_cap_mtd = 10.00;

-- Set $25/month budget for Smarter
INSERT INTO budgets (project_id, spend_cap_mtd) VALUES ('smarter', 25.00)
ON CONFLICT (project_id) DO UPDATE SET spend_cap_mtd = 25.00;

-- Set $15/month budget for Apparently
INSERT INTO budgets (project_id, spend_cap_mtd) VALUES ('apparently', 15.00)
ON CONFLICT (project_id) DO UPDATE SET spend_cap_mtd = 15.00;

-- View all budgets
SELECT * FROM budgets;
```

**Behavior:**
- Runner tracks spend per-project in `outcomes` table
- When project spend > budget cap → new task rejected + approval card (review cost first)
- Dashboard shows spend vs. cap (red warning if approaching limit)

---

## Step 5: Monitor Account Rotation

### Check Account Status

```bash
# See usage per account
supabase sql "
  SELECT 
    a.id, 
    a.usage_mtd, 
    COALESCE(SUM(o.cost), 0) as total_cost,
    COUNT(o.id) as task_count
  FROM accounts a
  LEFT JOIN outcomes o ON a.id = o.account_id
  GROUP BY a.id
  ORDER BY a.usage_mtd DESC;
"
```

### See Rotation Decisions

```bash
# Check runner heartbeats (includes account rotation log)
supabase sql "
  SELECT 
    runner_id, 
    last_seen, 
    status,
    metadata ->> 'active_account' as current_account
  FROM runner_heartbeats
  ORDER BY last_seen DESC;
"
```

### Manual Account Switch

If you need to use a different account temporarily:

```bash
# Edit runner/.env
nano runner/.env
# Change ANTHROPIC_API_KEY to different account key

# Restart runner
python3 runner.py
# Runner will use new primary account on next task
```

---

## Verification Checklist

### Before Going Live

- [ ] `runner/.env` configured with SUPABASE_SERVICE_KEY + 3x ANTHROPIC_API_KEY
- [ ] `.gitignore` includes `*.env` and `runner/.env`
- [ ] `git status` shows no `.env` files tracked
- [ ] Python deps installed: `pip3 install pyyaml`
- [ ] Web builds: `cd web && npm run build` (no errors)
- [ ] Runner starts: `python3 runner.py` polls Supabase
- [ ] Heartbeat appears: `SELECT * FROM runner_heartbeats` shows runner online
- [ ] Test task queued & executed (dry run)
- [ ] Dashboard shows completed task + spend
- [ ] Budget caps set per-project
- [ ] Account rotation tested (check heartbeat log)

### Post-Verification

- [ ] Set up launchd plist for runner (runs on startup)
- [ ] Enable Slack notifications (edge functions)
- [ ] Configure embedding provider (EMBED_PROVIDER in .env)
- [ ] Enable self-improvement loop (eval_harness.py)

---

## Commands Reference

```bash
# Start web dashboard (dev)
cd web && npm run dev

# Start runner (main loop)
cd runner && python3 runner.py

# Start runner with dry-run task
python3 runner.py --dry-run --task-id <task-id>

# Replay a failed task
python3 runner.py --replay-task <task-id>

# Run only tasks for one project
python3 runner.py --project-only tomorrow

# Generate contract-first task DAG
CLAUDE_BIN=claude python3 runner/planner.py "Build X end-to-end" > tasks.yaml

# Deploy web to Vercel
cd web && npm run build && npx vercel --prod

# Apply Supabase migrations
supabase db push

# Deploy Slack edge functions
supabase functions deploy

# Check Supabase connection
supabase status
```

---

## Troubleshooting

### Runner Won't Start

```bash
# Check Python version
python3 --version  # Should be 3.9+

# Install deps
pip3 install pyyaml supabase anthropic

# Check .env syntax
cat runner/.env | grep -E "SUPABASE|ANTHROPIC"

# Test Supabase connection
python3 -c "from supabase import create_client; ..."
```

### Tasks Stuck in PENDING

```bash
# Check runner heartbeat
supabase sql "SELECT * FROM runner_heartbeats ORDER BY last_seen DESC LIMIT 1;"

# If heartbeat is stale (>5 min ago), runner crashed
# Check runner terminal for errors

# If heartbeat is fresh but tasks pending, runner might be at MAX_PARALLEL limit
# Check running tasks: SELECT * FROM tasks WHERE status = 'RUNNING';
```

### Spend Higher Than Expected

```bash
# See which tasks cost the most
supabase sql "
  SELECT task_id, cost, tokens, model, created_at 
  FROM outcomes 
  ORDER BY cost DESC 
  LIMIT 10;
"

# See which projects are costing the most
supabase sql "
  SELECT t.project_id, COUNT(*) as task_count, SUM(o.cost) as total
  FROM outcomes o
  JOIN tasks t ON o.task_id = t.id
  GROUP BY t.project_id
  ORDER BY total DESC;
"

# Lower budget cap to prevent more overruns
supabase sql "UPDATE budgets SET spend_cap_mtd = 5.00 WHERE project_id = 'smarter';"
```

### Account Rotation Not Working

```bash
# Verify ACCOUNT_2_KEY, ACCOUNT_3_KEY in .env
cat runner/.env | grep ACCOUNT

# Check accounts table in Supabase
supabase sql "SELECT * FROM accounts;"

# If Account 2 usage is always 0, runner hasn't switched yet
# Try queuing enough tasks to exhaust Account 1, or manually edit heartbeat log
```

---

## Next Phase: Durability & Autonomy

Once verified, make the runner durability:

```bash
# Install launchd plist (runner survives logout)
bash scripts/setup-scheduler.sh

# Set up nightly self-review
# Set up hourly anomaly detection
# Set up 2-5 AM research window

# Enable Slack notifications
supabase functions deploy
# (add SLACK_WEBHOOK to .env)
```

---

**Status:** Ready for configuration. Follow Step 1 (runner/.env) to get live. 🚀
