# Portfolio Growth OS

A self-improving business-development / CRM / growth engine for the whole portfolio, built **as an
extension of the orchestrator** (Beethoven). The orchestrator is already a self-improving task
engine with a `gtm` task kind, an outcomes ledger, a capability registry, cross-app cost/quality
triage, and the Darwin attestation layer. Growth OS adds the missing growth-specific organs and
routes **human actions through Smarter**.

## The topology

```
  Products (tomorrow, apparently, smarter, pareto, racefeed, darwn, …)
     │  emit_growth_event()  (metadata only, no PII — actor is hashed)
     ▼
  ┌──────────────────────── Orchestrator Supabase (control plane) ─────────────────────────┐
  │  growth_events  ──►  compute_growth_momentum()  ──►  growth_momentum(_latest)           │
  │  growth_segments (bot-curated tree)  ──►  growth_arms (UCB1 bandit)                      │
  │  growth_content (corpus-fed pipeline)                                                    │
  │  tasks(kind='gtm')  +  approvals   ── the machine/human work queue & gates              │
  │  outcomes  ── $ + result ledger (already exists)                                         │
  └───────────────┬───────────────────────────────────────────────┬─────────────────────────┘
                  │ growth_momentum_latest                          │ growth_action_feed
                  ▼                                                 ▼
        Cockpit (cockpit.html)                              Smarter (human action surface:
        "where do I spend this week"                         task feed, approvals, CRM)
```

- **Engine = orchestrator.** It runs the growth agents, scores momentum, allocates the bandit,
  and drafts content — the same loop it already uses for code, pointed at growth.
- **Brain/credibility = the shared corpus + Darwin kernel** (authority + attestation).
- **Human surface = Smarter.** Everything that needs a human (approve a draft, send an outreach,
  make a call) lands in `growth_action_feed`, which Smarter renders as its task/approval inbox.

## What's in this folder

| File | What it is |
|---|---|
| `../supabase/migrations/0010_portfolio_growth_os.sql` | The whole schema: event bus, momentum engine, segment tree, bandit, content pipeline, action-feed view, RLS, and portfolio seed. Idempotent. |
| `sdk/emit.ts`, `sdk/emit.py` | Drop-in, fire-and-forget event emitters. Hash actor ids locally; never send PII; never break the app. |
| `cockpit.html` | Self-contained momentum cockpit. Reads `growth_momentum_latest` + `growth_action_feed`. |
| `content-engine/run.mjs` | Seeds the corpus-fed content pipeline: reads demand gaps from an app's corpus, files `gtm` draft tasks with grounded citations. |

## Deploy (≈30 min)

1. **Apply the migration** to the orchestrator DB (`claude-orchestrator`, ref `eatfwdzfurujcuwlhdgj`):
   `supabase db push` (or run `0010_portfolio_growth_os.sql` via the SQL editor / MCP). Safe to
   re-run. Edit the `growth_apps` seed tiers as strategy changes.
2. **Instrument the two spearheads first** (Tomorrow, Apparently). Add the SDK and emit the core
   funnel events at the real moments:
   - `visit` (landing view), `signup`, `activate` (first real use),
   - `qualified_lead` (demo booked / ICP-fit inbound), `revenue` (with `value` + `dedupKey`),
   - `content_published`, `churn`. Keep event-type + segment names STABLE.
   Set `ORCH_SUPABASE_URL`, `ORCH_SUPABASE_ANON_KEY`, `GROWTH_ACTOR_SALT` in each app's env.
3. **Schedule momentum.** Add a `loops` row (the orchestrator's cadence table) or a cron to call
   `select compute_growth_momentum();` every ~15 min.
4. **Stand up the cockpit.** Replace `%%SUPABASE_URL%%` / `%%SUPABASE_ANON_KEY%%` and serve it
   (drop into the orchestrator `web/public`, or open locally). Ranked apps + action feed appear.
5. **Wire Smarter.** Point a Smarter view at `growth_action_feed` (read) and let it write task
   status / approvals back. This makes Smarter the single human cockpit for all GTM work.
6. **Run the content engine.** `APP_NAME=apparently node content-engine/run.mjs` (then `tomorrow`).
   The swarm drafts, cite-checks, and repurposes; you approve in Smarter before publish.

## Live status (deployed to orchestrator DB `eatfwdzfurujcuwlhdgj`)

- `0010_portfolio_growth_os` — event bus, momentum, segments, bandit, content pipeline, action feed ✅
- `0011_growth_os_improvements` — plays, attestation, consented handoffs, confidence gate, weekly plan, answered-demand ✅
- `0012_growth_colosseum` — strategist roster (15), tournaments, ELO+calibration scoring, leaderboard ✅
- `0013_growth_comprehensive` — competitor intel, synth pre-test, prediction market, VoC, retention metrics, assets, pricing, attribution, ICP discovery, governance dial ✅
- **Apparently** wired: `server/utils/growth-os.ts` + `recordRevenue` hook + `/api/growth/visit` + `app/plugins/growth-os.client.ts`
- **Smarter** surface: `server/utils/orch.ts` + `/api/growth/feed` + `pages/growth.vue`
- See `COLOSSEUM.md` for the competitive-strategy engine design.

Env to set (Apparently + Smarter, from the orchestrator project settings): `ORCH_SUPABASE_URL`,
`ORCH_SUPABASE_ANON_KEY` (apps) / `ORCH_SUPABASE_SERVICE_KEY` (Smarter read), `GROWTH_ACTOR_SALT`.

## Guardrails (inherited from the orchestrator's own invariants)

- **No PII crosses the boundary.** Only hashed actors + metadata. Mirrors `privacy.scrub()` and the
  `app_triage` "metadata not payloads" rule.
- **Human gate before anything customer-facing** (send, publish, spend) via `approvals`.
- **Fail-soft everywhere.** Telemetry and content seeding never block a product.
- **RLS on all new tables.** NOTE: the pre-existing `app_operations`, `app_op_routes`,
  `shared_candidates` tables have RLS *disabled* — add policies (see main chat notes).

## The segment-of-one loop (how bots curate unique strategy per app → service → archetype → segment)

1. A **Growth Bot** per app decomposes app → products → archetypes → micro-segments into
   `growth_segments` (each a `path` like `apparently/licensing/dfs-startup/urgent-nj-pa`).
2. For each segment it writes **arms** (`growth_arms`) — variant {positioning, message, offer,
   landing}. `pick_growth_arm()` (UCB1) chooses which to serve; conversions feed `reward_sum`.
3. Winning arms propagate to sibling segments (reuse Smarter's cross-target learning pattern).
4. Momentum + corpus query-log measure whether it worked; losers are auto-retired; the loop tunes
   itself. You review only the exceptions Smarter surfaces.
