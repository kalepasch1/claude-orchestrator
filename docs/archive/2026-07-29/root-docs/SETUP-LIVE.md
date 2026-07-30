# Live setup — your provisioned project

The Supabase backend is **already created and seeded**. Project: `claude-orchestrator`
(ref `eatfwdzfurujcuwlhdgj`, region us-east-1, org vercel_icfg…). Schema applied, RLS on,
`accounts` locked to service-role only, and seeded with your `tomorrow` project, 6 tasks,
3 pending approvals, and cost history.

| Value | |
|---|---|
| Supabase URL | `https://eatfwdzfurujcuwlhdgj.supabase.co` |
| Anon key (web, public-safe) | in `web/.env` (already filled in) |
| Service role key (runner, SECRET) | **you copy this** — Supabase → Project Settings → API → `service_role` |
| Dashboard (Supabase) | https://supabase.com/dashboard/project/eatfwdzfurujcuwlhdgj |

## 1. Enable magic-link auth (1 min)
Supabase Dashboard → Authentication → Providers → **Email** → enable. Add yourself and
partners under Authentication → Users (or just sign in once; magic link self-registers).

## 2. Deploy the website to Vercel
The project is in the same Vercel org as your Supabase, so this is quick:
```
cd web
npm install
npm run dev          # local check at http://localhost:3000
```
Then deploy (either):
- **Vercel dashboard**: New Project → import this repo → **Root Directory = web/** →
  add env vars `SUPABASE_URL` and `SUPABASE_KEY` (from `web/.env`) → Deploy.
- **CLI**: `npm i -g vercel && cd web && vercel --prod` (set the two env vars when prompted).

## 3. Start the runner on your Mac
```
cd runner
cp .env.example .env
#  -> set SUPABASE_URL=https://eatfwdzfurujcuwlhdgj.supabase.co
#  -> set SUPABASE_SERVICE_KEY=<service_role key from the dashboard>   (keep secret!)
pip3 install pyyaml
set -a; . ./.env; set +a
python3 runner.py
```
The runner registers a heartbeat, claims QUEUED tasks, runs Claude Code in worktrees,
and reports back. The `tomorrow` project row already points at
`/Users/kpasch/Documents/tomorrow/tomorrow` — adjust if your path differs.

## 4. Use it
Open the Vercel URL → sign in → you'll see the seeded tasks, the 3 approvals (gitleaks
secret, the held payment-path commits, and a self-improvement proposal), and the spend
chart. Queue new work from the form, or generate a DAG:
`python3 runner/planner.py "Build X" > tasks.yaml`.

## Security notes
- `accounts` has RLS enabled with no policies → only the service-role runner can read it.
- The **service role key** must live ONLY on the runner (your Mac). Never put it in `web/`
  or commit it. The web app uses the anon key, gated by RLS + magic-link auth.
- Add a `.gitignore` with `.env` before pushing to GitHub.
