# Deploy — the 3 steps that are yours (and why)

The backend is live and seeded; the repo is committed locally. These three remaining
actions can't be done by my screen control, for specific safety reasons:
- **Service-role key** → I'm not permitted to enter secrets/keys into anything.
- **Terminal** → my screen access is read/click-only on terminals (no typing), so I
  can't run shell commands for you.
- **GitHub push** → needs your git credentials.

Each is copy-paste. I'm happy to walk you click-by-click (teach mode) if useful.

## 1. Email auth — already on ✅ (nothing to do)

## 2. Deploy the website to Vercel
```bash
cd /Users/kpasch/Documents/beethoven/claude-orchestrator/web
npm install
# push the repo to GitHub (or use `vercel` directly):
#   create a repo, then from the project root:
#   git remote add origin git@github.com:<you>/claude-orchestrator.git && git push -u origin master
npx vercel --prod        # set Root Directory = web/ , add env SUPABASE_URL + SUPABASE_KEY (from web/.env)
```
In the Vercel project: **Settings → Environment Variables** →
`SUPABASE_URL=https://eatfwdzfurujcuwlhdgj.supabase.co` and `SUPABASE_KEY=<anon key from web/.env>`.

## 3. Start the runner on your Mac
```bash
cd /Users/kpasch/Documents/beethoven/claude-orchestrator/runner
cp .env.example .env
#   edit .env:
#     SUPABASE_URL=https://eatfwdzfurujcuwlhdgj.supabase.co
#     SUPABASE_SERVICE_KEY=<service_role key — Supabase ▸ Project Settings ▸ API>
#     INTEGRATION_MODE=pr           # optional: PR-native integration (needs `gh` authed)
pip3 install pyyaml
set -a; . ./.env; set +a
python3 runner.py
```
The `tomorrow` project row already points at `/Users/kpasch/Documents/tomorrow/tomorrow`.

## Optional extras
- **Slack approvals:** deploy `supabase/functions/slack-notify` + `slack-interactions`
  (I can do this via the Supabase connector once you've made a Slack app + set the secrets),
  then add a Database Webhook on `approvals` INSERT → `slack-notify`.
- **Schedules:** point the v2 `scripts/setup-scheduler.sh` at this runner for the 2–5 AM
  research window, overnight deploys, nightly `self_review.py` + `anomaly.py` + `optimizer`.
