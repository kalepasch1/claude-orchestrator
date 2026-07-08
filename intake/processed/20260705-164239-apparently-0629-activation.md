PROJECT: apparently

# ACTIVATION — make the ALREADY-BUILT Hive engines (Phase 1-3, this session) reachable + usable by a real user NOW.
# These engines EXIST in code (server/engines/hive/*, server/engines/gaming-enablement/{sweeps-regime-classifier,
# support-entity-exposure}.ts, migrations 502_hive_innovation_layer + 503_hive_phase2) but have NO user-facing surface,
# no nav, no feature flag, and the migrations are not deployed. This workstream wires them end-to-end so a user can
# actually use them. Engines fail-open (return empty) when tables are absent, so UI renders before the deploy; the
# deploy + flag flip (OPERATOR) is the last mile to populate it. Conventions: typed SupabaseClient<Database>;
# requireAuth on user routes; logger; pure cores already tested. Depends in prose on migrations 502/503 being
# deployed (OPERATOR) to return live data — build the wiring regardless.

- id: act-hive-read-api
  title: Auth-gated GET API exposing coverage, reg_facts, candidates, autonomy, exposures, diffusion
  material: no
  model: sonnet
  depends: []
  proof: "`npx vitest run tests/api/hive/read-api.test.ts` exits 0 (each GET route returns typed data or a graceful empty payload when tables are absent; requireAuth enforced)"
  prompt: |
    Expose the built engines over user API. server/api/hive/: coverage.get.ts (coverageReport), reg-facts.get.ts
    (getCurrentFacts, filter by domain/jurisdiction/verticalKey, verified/current only), candidates.get.ts
    (hive_vertical_candidates), autonomy.get.ts (hive_vertical_autonomy), exposures.get.ts
    (support_entity_exposures by org), diffusion.get.ts (forecastSubjectDiffusion). All requireAuth, typed, fail-open
    to empty on missing tables. Unit-test each (mocked supabase, present + absent tables).

- id: act-regime-classifier-tool
  title: User-facing Regime A/B classifier tool (paste operator details → classification)
  material: no
  model: sonnet
  depends: []
  proof: "`npx vitest run tests/api/hive/regime-classify.test.ts` exits 0 (POST returns the deterministic-gate classification for dual-currency/one-off inputs; Regime B flagged needs_human_review) AND `npx vue-tsc --noEmit` exits 0 for the page"
  prompt: |
    server/api/hive/classify-regime.post.ts calls classifySweepsRegime (persist:false for the tool) + a page
    app/pages/hive/regime-classifier.vue: a form (dual-currency? redeemable? casino games? one-off?) → shows
    regime_a/regime_b/indeterminate + basis + needs-review badge. requireAuth. Unit-test the route; vue-tsc the page.

- id: act-exposure-and-arbitrage-tools
  title: Value-chain exposure preview + "what-if-banned" arbitrage/counter-arbitrage tool
  material: no
  model: sonnet
  depends: []
  proof: "`npx vitest run tests/api/hive/exposure-arbitrage.test.ts` exits 0 (exposure-preview returns computeExposures for a posted value-chain; what-if-banned returns detectArbitrage + counterArbitrage memo) AND `npx vue-tsc --noEmit` exits 0"
  prompt: |
    Two compute-only user tools. server/api/hive/exposure-preview.post.ts (computeExposures over a posted
    SupportRelationship[] + rule) and server/api/hive/what-if-banned.post.ts (detectArbitrage + counterArbitrage for a
    vertical + signals + trigger). Pages app/pages/hive/{exposure,what-if}.vue rendering flagged exposures (severity)
    and migration paths + illusory-escape residual risks. requireAuth, compute-only (no writes). Unit-test routes;
    vue-tsc pages.

- id: act-shared-artifact-reuse-widget
  title: Cross-vertical artifact reuse widget in onboarding (reuse/refresh/produce)
  material: no
  model: haiku
  depends: []
  proof: "`npx vitest run tests/api/hive/artifact-reuse.test.ts` exits 0 (POST returns planArtifactReuse reuse/refresh/produce plan for an org + required set) AND `npx vue-tsc --noEmit` exits 0"
  prompt: |
    server/api/hive/artifact-reuse.post.ts (planArtifactReuse) + a small widget component embeddable in the vertical
    onboarding flow showing which foundation artifacts reuse vs refresh vs produce (the dedup savings). requireAuth.
    Unit-test route; vue-tsc component.

- id: act-hive-nav-and-flag
  title: Nav section + HIVE_UI_ENABLED feature flag wiring all Hive surfaces reachable
  material: no
  model: sonnet
  depends: [act-regime-classifier-tool, act-exposure-and-arbitrage-tools]
  proof: "`npx vue-tsc --noEmit` exits 0 AND a nav test confirms an authed user with HIVE_UI_ENABLED sees the Hive section linking to regime-classifier, exposure, what-if, coverage, reg-facts, diffusion, candidates, autonomy"
  prompt: |
    Add a 'Regulatory Hive' nav section (reuse the existing nav/sidebar pattern) linking every Hive surface, gated by
    a HIVE_UI_ENABLED feature flag (default ON for the read/tool views — they're compute-only/read-only; material
    gates live elsewhere). Ensure each page is registered + routable. Prove vue-tsc clean + a nav visibility test.

- id: act-demo-seed
  title: Demo/seed path so the Hive UI is populated without waiting for live scouts
  material: yes
  model: sonnet
  depends: [act-hive-read-api]
  proof: "`npx vitest run tests/api/hive/demo-seed.test.ts` exits 0 (the seed inserts sample reg_facts incl. a support-entity fact + a sample classification; the read API then returns them; idempotent + gated to non-prod/admin)"
  prompt: |
    A guarded seed (admin/CRON-gated, non-prod default) server/api/hive/demo-seed.post.ts + script that inserts a
    representative set: a handful of gaming reg_facts across lifecycle stages, one NY support-entity prohibition fact,
    one sample sweeps_operator_classification, one candidate. Idempotent. This lets a user SEE the full experience
    immediately after the migrations deploy, before live scouts accumulate data. MATERIAL: writes data; gate to
    admin/non-prod. Unit-test seed + read-back.

- id: act-e2e-usable-smoke
  title: End-to-end smoke — a user can run classify → exposure → what-if → see facts
  material: no
  model: sonnet
  depends: [act-hive-nav-and-flag, act-demo-seed]
  proof: "`npx playwright test tests/e2e/hive-usable.spec.ts` exits 0 (an authed user opens the Hive section, runs a regime classification, previews an exposure, runs a what-if-banned, and browses seeded reg_facts — all succeed)"
  prompt: |
    Prove real usability. Playwright e2e (reuse the repo's playwright setup): authed user navigates the Regulatory
    Hive section, submits the regime classifier and sees a result, submits the exposure tool and sees a flagged
    exposure (from seed), runs what-if-banned and sees migration paths + residual risks, and browses seeded reg_facts.
    Green = the built Hive is genuinely usable by a user.

OPERATOR:
  - LAST-MILE TO LIVE (3 steps, human-only): (1) deploy migrations 502_hive_innovation_layer + 503_hive_phase2 to the prod Supabase project after name-check; (2) run `npm run gen:types`; (3) set HIVE_UI_ENABLED=true in prod. Until (1), the surfaces render but are empty (engines fail-open). Until (3), the nav is hidden. The wiring tasks above do everything that does NOT require prod DB/secret access.
  - Optionally run the demo-seed (admin) once post-deploy to populate the experience before live scouts accumulate.
