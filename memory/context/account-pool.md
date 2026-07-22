# Account Pool Configuration & Rotation

Context for managing multiple Anthropic API accounts across the orchestrator.

## Why Multiple Accounts?

- **Usage-based routing:** Some accounts have higher limits; rotate to balance load
- **Cost distribution:** Spread usage across accounts (if billing is per-account)
- **Redundancy:** If one account exhausted, seamlessly fail over to next
- **Rate limit avoidance:** Per-account rate limits; rotation spreads throughput

## Current Setup

You have **3 authorized accounts** registered in the orchestrator:

| Slot | Account | Status | Purpose | Usage Policy |
|------|---------|--------|---------|---------------|
| 1 | **Primary** | Active | Main workload | Use daily; monitor spend |
| 2 | **Secondary** | Standby | Overflow, high-volume | Activate when Account 1 exhausted |
| 3 | **Tertiary** | Standby | Research, batch jobs | Activate when 1+2 exhausted |

**Rule:** Only rotate accounts you're entitled to use. Respect Anthropic's usage policies.

## How account_pool.py Works

```python
# runner/account_pool.py
# 1. Loads ANTHROPIC_API_KEY + ACCOUNT_2_KEY, ACCOUNT_3_KEY from .env
# 2. Tracks usage (tokens, cost) per account in `accounts` table
# 3. When current account exhausted:
#    → Picks lowest-usage account
#    → Updates `runtimeConfig.anthropicApiKey`
# 4. Falls back to model heuristics (cost/throughput) when usage unclear
# 5. After ~100 tasks, bandit learning (UCB1) finds best model per workload
```

## Environment Setup (runner/.env)

```bash
# Primary account (required)
ANTHROPIC_API_KEY=sk-proj-your-primary-key

# Secondary account (optional but recommended)
ACCOUNT_2_KEY=sk-proj-your-secondary-key

# Tertiary account (optional)
ACCOUNT_3_KEY=sk-proj-your-tertiary-key
```

**Safety:** These are secrets — NEVER commit `.env` to git.

## Rotation Behavior

### Scenario 1: Normal Operation
- Account 1 is in use
- Bandit learning picks best model (e.g., Claude 3.5 Sonnet for most tasks)
- Dashboard shows cost/token metrics

### Scenario 2: Account 1 Exhausted
- account_pool.py detects usage near limit
- Checks Account 2 usage
- Switches to Account 2 automatically
- Next task runs on Account 2
- Dashboard shows account rotation in `runner_heartbeats`

### Scenario 3: All Accounts Exhausted
- Error → approval card on dashboard
- You must either:
  - Wait for usage to reset (daily/monthly limit)
  - Add a new account to `.env`
  - Contact Anthropic to increase limits

## Monitoring Account Usage

**Supabase:**
```sql
-- See usage per account
SELECT id, usage_mtd, model_stats FROM accounts;

-- See spend trend
SELECT account_id, SUM(cost) as total_cost FROM outcomes 
  GROUP BY account_id ORDER BY total_cost DESC;
```

**Dashboard:**
- "Spend" tab → shows cost by account
- "Runner Health" tab → shows account rotation status

## Switching Accounts Manually

If you need to switch accounts without waiting for exhaustion:

```bash
# Edit runner/.env
nano runner/.env
# Update ANTHROPIC_API_KEY to different account

# Restart runner
python3 runner.py  # Picks new account on next task
```

## Best Practices

1. **Monitor spend weekly** — catch overruns early
2. **Set budget caps** — `budgets` table per-project
3. **Rotate fairly** — don't exhaust one account while others idle
4. **Log rotations** — check `runner_heartbeats` for transparency
5. **Test new accounts** — use `--dry-run` before going live
6. **Keep secrets safe** — `.env` git-ignored, rotated keys in Supabase only

## Safety Guardrails

| Guardrail | How It Works | When It Triggers |
|-----------|--------------|------------------|
| **Per-project budgets** | `budgets` table: spend cap per project per month | Task cost > cap → reject + approval |
| **Account rotation** | Switch to next account when current exhausted | Usage threshold reached |
| **Verify step** | Cheap model reviews diff before integration | Risky changes require approval |
| **Approval cards** | Manual review queue on dashboard | Self-changes, budget overruns |
| **Cost logging** | All Claude calls recorded in `outcomes` | Audit trail + cost tracking |

## Troubleshooting

**Q: Account 1 is exhausted but Account 2 isn't picking up tasks**
- A: Check `runner/.env` — is `ACCOUNT_2_KEY` set? Restart runner.

**Q: Spend is higher than expected**
- A: Check `outcomes` table — see which projects/models are costliest
- A: Set lower `budgets` cap for high-spend projects
- A: Review model selection — maybe smaller model would work

**Q: Need to add a 4th account**
- A: Add to `runner/.env`: `ACCOUNT_4_KEY=sk-proj-...`
- A: Update `account_pool.py` if needed (should auto-detect)
- A: Restart runner

**Q: Want to disable Account 2 temporarily**
- A: Delete or comment out `ACCOUNT_2_KEY` in `runner/.env`
- A: Restart runner
