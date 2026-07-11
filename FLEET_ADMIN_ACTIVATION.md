# Fleet Admin — Activation Checklist (verified values)

Verified live via your Vercel dashboard on activation day. Exact URLs, domains, and the one
generated secret are filled in below.

## The generated shared secret (use the SAME value everywhere)
```
FLEET_SHARED_SECRET = 36bc6d4beb463e986767d5fb948926a19b41935beaab7fba0ebfbb33989934df
```
Treat this like a password. It authenticates plane↔app and plane↔Smarter calls.

## Why I can't finish this purely in Chrome (honest)
- **The new code isn't deployed.** Vercel builds from git; everything I wrote is in your local
  repos. `smarter` + `apparently` deploy on git push; the orchestrator `web` project is NOT
  git-connected and deploys via the `vercel` CLI. Env vars do nothing until the code ships.
- **I'm not allowed to type secrets into fields.** `FLEET_SHARED_SECRET` and any Supabase service
  key are secrets — you must paste those yourself. I can pre-fill the non-secret vars, but the
  secret rows are yours.
- Deploying (git push / `vercel --prod`) uses your credentials, which I correctly don't hold.

---

## Step 1 — Orchestrator (`web` project)
**Deploy (CLI, from your machine):**
```
cd <your path>/beethoven/claude-orchestrator/web
npm install            # pulls the vendored @darwin/kernel (file:../packages/darwin-kernel)
vercel --prod          # this project isn't git-connected — CLI deploy
```
**Env vars page:** https://vercel.com/kalepasch1s-projects/web/settings/environment-variables
Add these (Production). `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` are already injected by your
Supabase↔Vercel integration — my code reads either `SUPABASE_SERVICE_KEY` or `SUPABASE_SERVICE_ROLE_KEY`,
so you likely don't re-add them.

| Key | Value | Secret? |
|-----|-------|---------|
| `FLEET_SHARED_SECRET` | `36bc6d4b…934df` (value above) | 🔒 you paste |
| `FLEET_SHADOW_MODE` | `true` | plain |
| `ORCHESTRATOR_BASE_URL` | `https://web-six-chi-76.vercel.app` | plain |
| `SMARTER_INBOX_URL` | `https://smarter-nine.vercel.app/api/fleet/inbox` | plain |
| `FLEET_URL_APPARENTLY` | `https://apparently.vercel.app` | plain |

| `FLEET_URL_TOMORROW` | `https://<tomorrow-vercel-url>` | plain |
| `FLEET_URL_SMARTER` | `https://smarter-nine.vercel.app` | plain |
| `FLEET_URL_GALOP` | `https://<galop-console-vercel-url>` | plain |
| `FLEET_URL_HISANTA` | `https://admin-portal-nine-ochre.vercel.app` | plain |
| `FLEET_URL_PARETO` | `https://<pareto-vercel-url>` | plain |
| `OPS_EMAILS` | `kalepasch@gmail.com,kale@smrter.us` | plain |
| `ANTHROPIC_API_KEY` | your Claude API key (for NL Admin) | 🔒 you paste |
| `SUPABASE_URL_APPARENTLY` | `https://<apparently>.supabase.co` | plain |
| `SUPABASE_SERVICE_KEY_APPARENTLY` | apparently service role key | 🔒 you paste |
| `SUPABASE_URL_SMARTER` | `https://olaxnyrzoptjcntrrjgn.supabase.co` | plain |
| `SUPABASE_SERVICE_KEY_SMARTER` | smarter service role key | 🔒 you paste |
| `SUPABASE_URL_GALOP` | `https://qlzsnuspiypyejaqcdad.supabase.co` | plain |
| `SUPABASE_SERVICE_KEY_GALOP` | galop service role key | 🔒 you paste |
| `SUPABASE_URL_HISANTA` | `https://whhfugddqehxxbmwutsw.supabase.co` | plain |
| `SUPABASE_SERVICE_KEY_HISANTA` | hisanta service role key | 🔒 you paste |

After deploy, open **https://web-six-chi-76.vercel.app/admin** — Unified Admin Shell.
New: **https://web-six-chi-76.vercel.app/admin/chat** — NL Admin (ask questions in plain English).

## Step 2 — Smarter (`smarter` project) + your login
**Deploy:** commit + push the new fleet files to `kalepasch1/smarter` (git-connected → auto-builds),
or `vercel --prod` from `smarter/`.
**Env vars page:** https://vercel.com/kalepasch1s-projects/smarter/settings/environment-variables

| Key | Value | Secret? |
|-----|-------|---------|
| `FLEET_SHARED_SECRET` | same value as above | 🔒 you paste |
| `FLEET_APPROVER_EMAIL` | `kalepasch@gmail.com` | plain |

**Then sign in once** at `https://smarter-nine.vercel.app` as **kalepasch@gmail.com** (magic link /
Google) so the Supabase auth user exists. This is the single step only you can do — the approver
allowlist + fallback are already seeded in the DB. Then open `https://smarter-nine.vercel.app/fleet`.

## Step 3 — All child apps (same 2 env vars each)

Every child app needs these two env vars. Add in each app's Vercel env settings:

| Key | Value | Secret? |
|-----|-------|---------|
| `FLEET_SHARED_SECRET` | same value as orchestrator | 🔒 you paste |
| `ORCHESTRATOR_INGEST_URL` | `https://web-six-chi-76.vercel.app/api/fleet/ingest` | plain |

App-specific env pages:
- **Apparently** — https://vercel.com/kalepasch1s-projects/apparently/settings/environment-variables
- **HiSanta** — https://vercel.com/kalepasch1s-projects/admin-portal/settings/environment-variables
- **Tomorrow / Galop / Pareto** — find in your Vercel dashboard

## Step 4 — Run fleet_policies migration

Open the orchestrator Supabase SQL Editor:
`https://supabase.com/dashboard/project/eatfwdzfurujcuwlhdgj/sql`

Paste and run the contents of `web/supabase/migrations/001_fleet_policies.sql`.

## Step 5 — Commit + deploy

```bash
# Repos with git: orchestrator, smarter, apparently, hisanta
cd ~/Documents/beethoven/claude-orchestrator && git add -A && git commit -m "fleet admin: NL chat, proxy layer, policy engine, cascade engine"
cd ~/Documents/smarter && git add -A && git commit -m "fleet admin: execute endpoint, adapter, auth hardening"
cd ~/Documents/apparently && git add -A && git commit -m "fleet admin: execute endpoint, adapter, event wiring"
cd ~/Documents/hisanta && git add -A && git commit -m "fleet admin: execute endpoint, CORS fix, auth fix"

# Push git-connected repos (auto-deploys)
cd ~/Documents/smarter && git push
cd ~/Documents/apparently && git push
cd ~/Documents/hisanta && git push

# CLI deploy for orchestrator
cd ~/Documents/beethoven/claude-orchestrator/web && npm install && vercel --prod
```

---

## Confirm it's working
1. `https://web-six-chi-76.vercel.app/api/fleet/kpi` and `/api/fleet/eval` show real volume (not 0).
2. Monday's `fleet-shadow-monitor` scheduled task reports the would-decision distribution + a
   PASS/FAIL safety check (no always-escalate verb ever landed auto). Read it before leaving shadow.
3. After ~a week clean, set `FLEET_SHADOW_MODE=false` and accept the safest promotions from
   `/api/fleet/self-promotion`.

**Tell me once Smarter is deployed + you're logged in** and I'll run a live round-trip through the
real HTTP feed (ingest → govern → approve in Smarter → callback → execute) to confirm the last hop.
