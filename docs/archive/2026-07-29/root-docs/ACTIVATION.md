# Safe activation — read before unpausing

Cowork wired and tested the spend controls in code (this session). The system is still
**globally PAUSED on purpose**: the currently-running runner process has the OLD code, so
it must be restarted to pick up these fixes BEFORE the pause is lifted. Unpausing the old
process would spend uncapped.

## What changed in code (all tested)
- `claude_cli.py` — safe default caps **$40/day, $10/hr, 80 calls/hr** (even if `.env` is absent).
- `runner.py` — the main task call now goes through `claude_cli` (real cost capture + kill switch + circuit breaker); a **waste guard** pauses any project that spends >$5 in 6h while shipping nothing; the **scheduler skips model-spending jobs while paused**.
- `verify.py`, `confidence.py` — the per-task model calls also route through `claude_cli` (so the $40/day cap is accurate, not just the main call).
- `account_pool.py` — accounts now load from Supabase (priority 1 `kalepasch@gmail.com` = default login, failover 2 `kale@heretomorrow.us`); rotation persists to the DB + alerts via `notify`.

## What YOU need to do (in order)

1. **Log in the failover account** (one time), so rotation actually works while account 1 is weekly-capped:
   ```bash
   CLAUDE_CONFIG_DIR=~/.claude-heretomorrow claude login   # sign in as kale@heretomorrow.us
   ```
2. *(optional, recommended)* add to `runner/.env` to lock the caps explicitly:
   ```
   CLAUDE_MAX_USD_PER_DAY=40
   CLAUDE_MAX_USD_PER_HOUR=10
   CLAUDE_MAX_CALLS_PER_HOUR=80
   ENABLE_PROACTIVE_LOOPS=false
   ```
3. **Restart the runner** so it loads the new code (and remove the launchd respawn if you want a clean single process):
   ```bash
   pkill -9 -f runner.py ; sleep 2
   cd ~/Documents/beethoven/claude-orchestrator/runner && python3 runner.py
   ```
4. Tell Cowork the **repo paths** for the apps not yet registered (darwn, smarter, pareto-2080, santas-secret-workshop, racefeed). The runner reads them by path on the Mac — Cowork doesn't need to mount them, just insert the rows.
5. Then Cowork lifts the pause and the fleet runs governed.

## "All 8–9 simultaneously" — the honest version
True 9-way parallel Claude sessions is the exact thing that caused your original rate-limit
storms. All projects are **active** (the queue works each over time, ROI-weighted), but
concurrency stays low (`MAX_PARALLEL=2`, throttled further under disk/RAM pressure). With two
subscriptions + a $40/day cap, that's the throughput that won't trip limits — "always
improving," not "always colliding."

## Residual gap (disclosed, not hidden)
~15 lower-frequency scheduled callers (self_review, scout, meta_loop, etc.) still call the CLI
directly. They are now **gated by the kill switch when paused** and off by default
(`ENABLE_PROACTIVE_LOOPS=false`), but when running they aren't yet counted against the $40/day
cap. Routing them through `claude_cli` too is the clean follow-up (mechanical, ~15 files).
