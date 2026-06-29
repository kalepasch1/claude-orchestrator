# Master setup prompt — paste this into the Claude Code session in VS Code

> Copy everything in the fenced block below into Claude Code (running in this repo,
> `/Users/kpasch/Documents/beethoven/claude-orchestrator`). It has your terminal,
> your git/GitHub credentials, and the `claude` CLI — so it can finish the exact
> steps Cowork could not (push to GitHub, deploy to Vercel, and start the runner
> with your secret service-role key). Work through it phase by phase.

```
You are finishing the deployment of the "Claude Orchestrator" in THIS repo
(/Users/kpasch/Documents/beethoven/claude-orchestrator). Context you can trust:

- The Supabase backend is ALREADY LIVE and seeded.
    URL : https://eatfwdzfurujcuwlhdgj.supabase.co   (ref: eatfwdzfurujcuwlhdgj)
    Schema applied (projects, tasks, approvals, outcomes, accounts, runner_heartbeats,
    knowledge, budgets, failures + v_spend_mtd). Seeded with the `tomorrow` project,
    6 tasks, 3 approvals, cost history.
- `web/.env` already has SUPABASE_URL + the public ANON key (safe to expose).
- The SERVICE-ROLE key is NOT in the repo and must never be committed. When you need
  it, ASK ME to paste it, or tell me to put it in `runner/.env` myself.
- Architecture: a hosted Nuxt+Tailwind site on Vercel (control plane) + a Python
  runner on this Mac that executes Claude Code and reports to Supabase.

Rules:
- NEVER commit secrets. Confirm `.gitignore` covers `.env`, `runner/.env`, `node_modules`.
- Work in small steps; run builds/tests; show me a checklist at the end.
- Pause and ASK before anything destructive or anything needing my credentials/keys.

PHASE 1 — Web app builds locally (do this FIRST; it was never compiled).
1. `cd web && npm install`.
2. `npm run build`. Fix any errors until it builds clean. Likely fix points:
   - The Chart.js dynamic import in `pages/index.vue` uses a CDN ESM URL
     (`import('https://cdn.jsdelivr.net/npm/chart.js@4.4.3/+esm')`). If the build or
     SSR chokes on it, install chart.js as a dep (`npm i chart.js`) and import it
     normally inside the client-only `renderChart()` instead of the CDN URL.
   - Ensure `@nuxtjs/supabase` + `@nuxtjs/tailwindcss` are installed and that
     `redirect: false` is honored (auth is handled inline on the index page).
   - Confirm Tailwind processes `assets/main.css`.
3. `npm run dev` and load http://localhost:3000 — confirm the magic-link sign-in screen
   renders. (You won't be signed in yet; just confirm no console errors.)

PHASE 2 — Deploy the website to Vercel.
1. Ensure a clean git state at the repo root; create `.gitignore` entries if missing.
2. Create a GitHub repo and push (use my `gh`/git creds):
   `gh repo create claude-orchestrator --private --source=. --remote=origin --push`
3. Deploy with Vercel, Root Directory = `web/`:
   `cd web && npx vercel link` then `npx vercel --prod` (or `gh`/dashboard import).
4. Set Vercel env vars (Project → Settings → Environment Variables), Production+Preview:
   `SUPABASE_URL=https://eatfwdzfurujcuwlhdgj.supabase.co`
   `SUPABASE_KEY=<the anon key from web/.env>`
   Redeploy so they take effect.
5. Open the deployed URL, sign in with a magic link (Supabase email auth is ON), and
   confirm you see the seeded tasks, the 3 approvals (with Why/Value/Risk), the budget
   bars, and the spend burn-down chart. Report the live URL to me.

PHASE 3 — Start the runner on this Mac.
1. `cd runner && cp .env.example .env`.
2. Ask me for the SERVICE-ROLE key (Supabase ▸ Project Settings ▸ API ▸ service_role)
   and have me put it in `runner/.env` as `SUPABASE_SERVICE_KEY=...`. Also set:
   `SUPABASE_URL=https://eatfwdzfurujcuwlhdgj.supabase.co`
   `MAX_PARALLEL=2`   `TEST_CMD="npm test"`   (optional: `INTEGRATION_MODE=pr`)
3. `pip3 install pyyaml`. Confirm `claude` CLI is authenticated (it is — you're it).
4. Make sure git identity is set (worktrees need it): `git config --global user.email`
   and `user.name` if unset.
5. Verify the `tomorrow` project row's `repo_path` is correct for this machine
   (it's `/Users/kpasch/Documents/tomorrow/tomorrow`); fix via a Supabase update if not.
6. Start it: `set -a; . ./.env; set +a; python3 runner.py`. Confirm a row appears in
   `runner_heartbeats` and the dashboard shows the runner ONLINE.

PHASE 4 — End-to-end smoke test.
1. From the deployed dashboard, queue a tiny task in a SAFE throwaway repo (or a
   `--dry-run`-style no-op prompt) and confirm: runner claims it → state RUNNING →
   verify → integrate → outcome + cost row appear → dashboard updates live.
2. Approve one of the seeded approvals from the dashboard and confirm its status flips.

PHASE 5 — Make it durable + autonomous (critical for "always running").
1. Install the schedulers (launchd) so it survives logout and runs continuously:
   reuse `../claude-orchestrator/scripts/setup-scheduler.sh` patterns OR write launchd
   plists for: (a) the runner (KeepAlive), (b) nightly `self_review.py`, (c) hourly
   `anomaly.py`, (d) the 2–5 AM research window, (e) overnight deploy window.
2. Set a sensible per-project budget in the `budgets` table for each real project.
3. Confirm secrets hygiene: `git status` clean, no `.env` tracked, `git log -p | grep -i
   service_role` returns nothing.

PHASE 6 — Optional (ask me first).
- Deploy the Slack edge functions in `supabase/functions/` and add a Database Webhook
  on `approvals` INSERT → `slack-notify`, so I can approve from my phone. Needs a Slack
  app + the SLACK_* secrets.
- Run `synthesize_conventions.py` against my real repos to generate their CLAUDE.md
  (enables prompt-cache savings).

FINISH: give me a checklist of what's deployed, the live Vercel URL, the runner status,
anything you changed in the code to make it build, and any decisions you need from me.
```
