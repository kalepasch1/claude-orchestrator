# Memory System — Claude Orchestrator

This folder contains shared knowledge about the Claude Orchestrator project, enabling Claude to work in this codebase with full context.

## Files

- **glossary.md** — Decoder ring for shorthand (acronyms, project names, registered projects, accounts)
- **index.md** — Quick reference + shortcuts Claude understands
- **projects/orchestrator.md** — Detailed project info (setup status, architecture, commands, debugging)
- **context/account-pool.md** — Multi-account rotation system (3 accounts, monitoring, troubleshooting)

## How It Works

When Claude is invoked in this directory:

1. Claude loads `/CLAUDE.md` (hot cache with tech stack, commands, conventions)
2. Claude references this memory/ for full context on:
   - Project terminology (DAG, runner, UCB1, verify step, etc.)
   - Registered projects (Tomorrow, Smarter, Apparently)
   - Account rotation system (3 accounts, fallback behavior)
   - Debugging tips and common tasks

## Example: Decoding Shorthand

```
User: "Queue a task for tomorrow on account 2"

Claude resolves:
  "tomorrow" → Tomorrow Warroom project (/Users/kpasch/Documents/tomorrow/tomorrow)
  "account 2" → Secondary account (account_pool.py rotates to this)
  "queue a task" → Use web dashboard or API to insert task into Supabase

Now Claude can execute with full context.
```

## For Developers

When you make changes:

1. **New feature or script?** Add to glossary.md or projects/orchestrator.md
2. **New account added?** Update context/account-pool.md
3. **New project to orchestrate?** Add to glossary.md `Projects Registered` table
4. **New convention or safeguard?** Add to CLAUDE.md or this memory

This keeps memory fresh and relevant.

## Auto-Switching Between Projects

The orchestrator is designed to work alongside two other projects (Tomorrow, Smarter, Apparently):

- **Tomorrow:** Legal workspace — `memory/` in that folder has its own context
- **Smarter:** AI legal assistant — same pattern
- **Apparently:** Core tech — same pattern

When you switch folders, Claude automatically loads the relevant CLAUDE.md + memory/.

**This orchestrator's role:** Executes tasks across all three in parallel, learning from outcomes.
