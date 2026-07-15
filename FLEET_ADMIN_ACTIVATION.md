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

After deploy, open **https://web-six-chi-76.vercel.app/fleet** — Mission Control.

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

## Step 3 — Apparently (`apparently` project) + shadow emitter
**Deploy:** push the adapter files to `kalepasch1/apparently` (git-connected → auto-builds).
**Env vars page:** https://vercel.com/kalepasch1s-projects/apparently/settings/environment-variables

| Key | Value | Secret? |
|-----|-------|---------|
| `FLEET_SHARED_SECRET` | same value | 🔒 you paste |
| `ORCHESTRATOR_INGEST_URL` | `https://web-six-chi-76.vercel.app/api/fleet/ingest` | plain |

**Turn on the emitter.** Dry-run first (no writes):
```
cd <your path>/apparently
node scripts/fleet-shadow-emit.mjs --dry
```
Then schedule it (crontab example, every 15 min):
```
*/15 * * * * cd <your path>/apparently && node scripts/fleet-shadow-emit.mjs >> /tmp/fleet-emit.log 2>&1
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
