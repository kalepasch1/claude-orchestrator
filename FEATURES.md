# v3.1 — the eight features

All eight are implemented in `runner/` (+ `supabase/functions/` + dashboard) and compile/
smoke-test clean. Enable each via env or task `kind`.

### 1. PR-native integration (`pr_integrate.py`)
Set `INTEGRATION_MODE=pr` (needs `gh` authed on the runner). Instead of a local merge, the
runner pushes the branch, opens a GitHub PR with the verification + test summary, polls your
real CI (sfc / gitleaks / vercel / preflight), and `--auto`-merges on green. Partners get a
review trail. `PR_AUTO_MERGE=false` to leave PRs open for manual merge.

### 2. Slack phone approvals (`supabase/functions/slack-notify`, `slack-interactions`)
Deploy both edge functions; add a Database Webhook on `approvals` INSERT → `slack-notify`.
New approvals post to Slack with **Approve/Deny** buttons; clicks hit `slack-interactions`
which updates the row (and the web dashboard updates in realtime). Secrets:
`SLACK_BOT_TOKEN`, `SLACK_CHANNEL`, `SLACK_SIGNING_SECRET`. (The dashboard is already
mobile-responsive, so phone approvals work via the web app too.)

### 3. Speculative N-best (`speculative.py`)
Queue a task with `kind='speculative'`. The runner races Haiku/Sonnet/Opus in separate
worktrees, tests each, and keeps the **cheapest that passes** (discards the rest). Big
quality/latency win on hard tasks for a little extra spend.

### 4. Regression memory (`regression.py` + `failures` table)
Every BLOCKED/TESTFAIL/verify-fail records the approach + root cause. Future similar tasks
get an **"avoid these mistakes"** preamble. Ships seeded with your real incidents
(raw-SQL-in-zsh, fail-open allowlist, same-file conflicts, committed secrets).

### 5. Auto-CLAUDE.md synthesis (`synthesize_conventions.py`)
`python3 synthesize_conventions.py <repo>` (schedule weekly). A cheap model writes/refreshes
each repo's `CLAUDE.md` (stack, commands, do/don't). That file is the cached prefix
(`caching.py`) → builds get more on-style **and** cheaper as caching compounds.

### 6. Budget guardrails + live charts (`budget.py` + `budgets` table + dashboard)
Set a monthly cap per project (`budgets` table; `tomorrow` seeded at $200). The runner checks
month-to-date spend before each task and **pauses** the project at the cap (files an approval
to raise it). Dashboard shows per-project budget bars + a Chart.js spend burn-down.

### 7. Runner fleet autoscaling (`db.claim_task` + dashboard fleet view)
`claim_task` is an atomic optimistic claim, so you can run `runner.py` on **multiple machines**
(Mac + cloud VMs) and they shard the queue safely. Each posts a heartbeat; the dashboard shows
the live fleet. Scale throughput by adding runners.

### 8. Anomaly alerts (`anomaly.py`)
Schedule hourly. Compares the recent window vs baseline for fail-rate, cost-per-task, and
rate-limit frequency; spikes file a self-alert approval card. The self-loop watching its own
vitals so regressions surface before a big bill or a stalled fleet.
