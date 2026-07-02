# Growth OS — Activation Runbook

Everything is built, deployed (24 migrations on orchestrator DB `eatfwdzfurujcuwlhdgj`), and OFF by
default. This is the exact sequence to take it live safely and watch one full loop.

## 0. Where you manage it
- **Smarter (you, day-to-day):** `/growth-admin` (control: switches, campaigns, kill switch),
  `/growth` (momentum + action feed + leaderboard), `/design` (Creative Studio).
- **Orchestrator (oversight):** `/growth` (marketing momentum → budget → AI token spend → focus).
- **Continuous learning:** runner loops `growth_learn` (1h), `colosseum` (1h), `bd_autopilot` (15m),
  `creative_gen` (10m). They only act within the switches; nothing sends/spends until you turn it on.

## 1. Environment variables

**Smarter + Apparently** (`.env` / Vercel):
```
ORCH_SUPABASE_URL=https://eatfwdzfurujcuwlhdgj.supabase.co
ORCH_SUPABASE_ANON_KEY=<orchestrator anon key>         # apps emit events
ORCH_SUPABASE_SERVICE_KEY=<orchestrator service key>   # Smarter reads feeds/queues
GROWTH_ACTOR_SALT=<random secret, same value everywhere>
RESEND_API_KEY=<resend key>            # real email send (else fail-soft = records intent only)
OUTREACH_FROM_EMAIL=you@yourdomain.com
SMARTER_AUTOPILOT_URL=https://<smarter-host>/api/growth/autopilot   # runner drives the tick
BD_MIN_LEAD_SCORE=0                     # raise later to skip low-fit leads
BD_MIN_CONFIDENCE=0.7                   # reply auto-handle threshold (self-tightens)
```

**Orchestrator runner** (already has SUPABASE_URL/SERVICE_KEY):
```
ENABLE_PROACTIVE_LOOPS=true
ANTHROPIC_API_KEY=<key>                 # provider for app_triage generation
IMAGE_GEN_URL=<image-gen endpoint>      # optional: Creative Studio generation
VISION_SCORE_URL=<vision brand-scorer>  # optional: auto brand-score triage
PORTFOLIO_WEEKLY_BUDGET=0               # >0 turns on budget rebalancing
BD_AUTOPILOT_APPS=apparently,smarter,tomorrow
```

## 2. Preflight
```
bash growth-os/activate-preflight.sh
```
Confirms env is set, the orchestrator REST + RPCs answer, the loops exist, and the global switch is OFF.

## 3. Start the engine
Run the Mac runner (per `DEPLOY.md`) with the launchd job pointed at `runner/`. Confirm heartbeats
in `runner_heartbeats` and that `loops.run_due()` fires (`resource_events` gets `colosseum_tick` /
`growth_learn` rows).

## 4. Instrument Apparently (real data)
The emit calls are already in `revenue-tracker.ts` + the visit plugin. Deploy Apparently with the env
above; `visit` / `signup` / `revenue` events start landing in `growth_events`, and momentum,
attribution, and the world-model run on live numbers.

## 5. Bring up ONE campaign (5 minutes, safe)
In Smarter `/growth-admin`:
1. **Create campaign** — name it, app `apparently`, segment `apparently/licensing/dfs-startup/urgent-nj-pa`, mode **Approval**, ramp 25. (Staged; still can't send.)
2. **Enqueue contacts** — POST `/api/growth/autopilot {action:'enqueue', app:'apparently', actorHash, segment}` for ~25 real contacts (hash their ids; supply resolvable send addresses to the email connector).
3. **Turn on switches** — set **global → Approval** and app `apparently` → Approval. (Auto is still off; every contact needs your OK.)
4. **Approve one contact** in the action feed. The next `bd_autopilot` tick drafts (via `llm.ts`),
   passes the policy + gate, sends (via Resend), emits `outreach_sent`, and learns.
5. **Watch the loop:** `/growth` momentum + action feed, `/design` for any visuals, Orchestrator
   `/growth` for spend↔tokens. Reply handling: POST `/api/growth/autopilot {action:'reply', outreachId, intent, confidence}`.

## 6. One-contact dry run (no real send)
Leave `RESEND_API_KEY` unset (connector fail-soft): enqueue 1 contact, approve it, trigger a tick —
you'll see `outreach_sent` recorded and the state machine advance with zero real email. Perfect for a
rehearsal.

## 7. Prove value, then widen
- After real revenue flows, read `counterfactual_value()` — incremental conversions vs. baseline.
- Then add the 2nd app, connect an ad account (`growth_ad_accounts` + `sync_ad_performance`), and let
  `compounding_dividend()` propagate the first wins.

## Emergency stop
Smarter `/growth-admin` → **Kill switch** (or `select pause_all_outreach();`). Instantly halts all
outreach everywhere; the circuit breaker also auto-pauses any campaign whose health drops.
