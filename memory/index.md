# Memory Index — Claude Orchestrator

This memory system enables Claude to understand orchestrator shorthand and context automatically.

## Structure

```
memory/
  index.md                          ← You are here
  glossary.md                       ← Full decoder ring (terms, acronyms, projects)
  projects/
    orchestrator.md                 ← Detailed project info + setup status
  context/
    account-pool.md                 ← Multi-account rotation system
```

## Auto-Loading

When Claude is invoked in `/Users/kpasch/Documents/beethoven/claude-orchestrator`:

1. **Hot cache (CLAUDE.md):** Loads immediately — tech stack, commands, conventions
2. **Memory lookup:**
   - Check glossary.md for terms (DAG, runner, UCB1, etc.)
   - Check projects/orchestrator.md for project details
   - Check context/account-pool.md for account rotation info
3. **Automatic context switching:** Understands you're working on orchestrator tasks

## Quick Reference

| Need to Know | File |
|--------------|------|
| What does "UCB1" mean? | glossary.md |
| How does the runner work? | projects/orchestrator.md |
| Where do I set API keys? | context/account-pool.md |
| What are the commands? | CLAUDE.md (top of repo) |
| How do I debug a task? | projects/orchestrator.md → Common Tasks |

## Shortcuts

**Common shorthand Claude understands:**

- "Queue a task for tomorrow" → Tomorrow project (registered in Supabase)
- "Check the spend" → Dashboard spend tab
- "Approve the card" → Web dashboard approvals queue
- "The runner is down" → Python runner on your Mac (launchd)
- "Rotate accounts" → account_pool.py automatically does this
- "Self-review proposed X" → eval_harness.py improvements (approval-gated)

## Updating Memory

When things change, update these files:

- **New project registered?** → Add to glossary.md `Projects Registered` table
- **New account added?** → Update context/account-pool.md
- **New tool/script created?** → Add to projects/orchestrator.md
- **New convention learned?** → Add to CLAUDE.md `DO/DON'T` or glossary.md

## Account Switching (3-Account Setup)

This orchestrator automatically manages 3 authorized Anthropic accounts:

| Account | Role | Auto-Switch When |
|---------|------|------------------|
| Account 1 (Primary) | Main workload | Always first choice |
| Account 2 (Secondary) | Overflow | Account 1 exhausted |
| Account 3 (Tertiary) | Batch/research | Accounts 1+2 exhausted |

See `context/account-pool.md` for setup & monitoring.

## Next Steps

1. **Run `/productivity:start`** to sync this memory with your task lists & projects
2. **Verify auto-switching** by queuing a task and confirming runner picks it up
3. **Monitor spend** on the dashboard
4. **Set budget caps** per-project in Supabase `budgets` table
