# Launch QA Full Sweep — every page, feature, function, API (operator, 2026-07-31)

Comprehensive QA across apparently (apparently.cc), apparently-law (apparentlylaw.com), tomorrow
(heretomorrow.us), pareto-2080 (joinpareto.us), smarter (smrter.us). High CADE scrutiny. Decompose
per app x per layer; every finding either FIXED in the same shard (small) or queued as a fix task
(large) — never report-only.

LAYERS per app:
1. ROUTES: crawl every page route; assert 200/expected-auth-redirect, no console errors, no dead
   links, no hydration errors, mobile viewport renders.
2. APIS: enumerate server routes; probe auth gates (401/403 where required, 2xx where public),
   Zod/schema validation on bad input, rate-limit + webhook exemptions (REGRESSION: the Stripe
   webhook 403 class fixed in apparently agent/stripe-webhook-exempt-fix — verify equivalents in
   EVERY app: any S2S webhook path must be exempt from csrf/bot-guard/auth middlewares and
   verified by signature in-handler).
3. FEATURES/FLOWS: signup -> core value -> payment -> admin. For apparently: token terms + purchase
   + burn metering. For tomorrow: IOI publish/discover, mesh, provision flows. For pareto: consumer
   signup + plan views (must read only via v_*/cade_* views post-RLS-lockdown — verify no client
   query hits a raw table). For smarter: workspace + linkage bridge to apparently.
4. AGENTS/BOTS: every registered bot has a live schedule + recent heartbeat/run; no silent .err
   growth (silent_failure_guard pattern); cron routes all resolve.
5. SECURITY REGRESSION: re-run the advisor checklist per app (RLS enabled everywhere, no
   anon-callable SECURITY DEFINER mutators, search_path pinned, leaked-password protection noted).
6. PAYMENTS/ADMIN/LEGAL/CS: billing pages load; admin boards reachable by admin only; legal pages
   (ToS, privacy, disclosures) present + linked in footer; support/contact path works end-to-end.
Produce a per-app scorecard artifact in the repo (docs/QA_LAUNCH_SCORECARD.md) with pass/fail per
layer + links to fix shards. All commits kalepasch1 <kalepasch@gmail.com>.
