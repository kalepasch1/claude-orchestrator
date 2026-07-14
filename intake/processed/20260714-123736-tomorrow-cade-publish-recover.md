PROJECT: tomorrow
# Publishing pipeline + tier-edge report. Chains onto cade-publication-extract + cade-mispricing-radar.

- id: cade-publish-store
  title: Prisma store for articles, review queue, and publish log
  material: yes
  model: sonnet
  depends: [cade-publication-extract]
  proof: `npx prisma validate` exits 0 AND `npx vitest run server/utils/cade/__tests__/publishStore.test.ts` exits 0
  prompt: |
    Add Prisma CadeArticle/CadePublishReview/CadePublishLog (idempotent migration, admin-only
    RLS). server/utils/cade/publishStore.ts pure state-machine (draft->ready_for_review->
    approved->published) via publishPlan. Test transitions. Do NOT deploy migration (OPERATOR).

- id: cade-tiered-gate-reconcile
  title: Reconcile server publishGate + admin console to the tiered model
  material: no
  model: sonnet
  depends: [cade-publish-store]
  proof: `npm run build` exits 0 AND `npx vitest run packages/cade-publication` exits 0
  prompt: |
    evaluatePublishTier as single source of truth across track-record route + admin console
    (per domain: tier, accuracy vs 80%/90%, ECE, n, progress 100->1000->5000; conservative=
    website-only highlights, moderate=+Medium cadence, full=all predictions).

- id: cade-website-insights
  title: Public /insights blog pages with JSON-LD + sitemap + RSS (SEO)
  material: no
  model: sonnet
  depends: [cade-publish-store]
  proof: `npm run build` exits 0
  prompt: |
    pages/insights/index.vue + [slug].vue via channels.articleToHtml + seo.jsonLd (useHead,
    canonical, OG). sitemap.xml + /insights/rss.xml over published + internal linking. Website
    is SEO canonical; only status=published renders.

- id: cade-medium-adapter
  title: Medium publishing channel (canonical back to website)
  material: yes
  model: sonnet
  depends: [cade-publish-store]
  proof: `npm run build` exits 0 AND `npx vitest run server/utils/cade/__tests__/mediumAdapter.test.ts` exits 0
  prompt: |
    server/utils/cade/mediumAdapter.ts posts approved articles to Medium (buildMediumPayload,
    canonicalUrl->website). Token MEDIUM_INTEGRATION_TOKEN (OPERATOR); network behind injected
    client, test with fake (no network). Only status=approved. Material: external publish.

- id: cade-hivemind-drafting
  title: Experts draft articles (individual / group / full hivemind) into the review queue
  material: yes
  model: opus
  depends: [cade-publish-store]
  proof: `npm run build` exits 0 AND `npx vitest run server/utils/cade/__tests__/hivemindDrafting.test.ts` exits 0
  prompt: |
    Experts DRAFT: validated theory->buildTheoryWhitepaper; qualifying track record->
    buildTrackRecordArticle; hivemind mode composes multiple experts w/ attribution. Drafts ->
    review queue (ready_for_review) w/ backing stats. LLM polish=logged AI path; assembly pure+
    tested. Material: content (human-reviewed).

- id: cade-admin-console
  title: Admin console - monitor learning progress + review/approve publications
  material: no
  model: sonnet
  depends: [cade-website-insights, cade-hivemind-drafting]
  proof: `npm run build` exits 0
  prompt: |
    pages/app/admin/cade-publishing.vue: per-domain gate progress + tier + accuracy trend;
    draft review queue w/ one-click Approve->publish (website+Medium), Reject, Edit; theory
    leaderboard + product-mint proposals. Writes=review decisions. Waits for human until
    CADE_PUBLISH_AUTONOMOUS.

- id: cade-bizdev-distribution
  title: Auto-generate the distribution pack and queue it to marketing orchestration
  material: no
  model: sonnet
  depends: [cade-hivemind-drafting]
  proof: `npm run build` exits 0 AND `npx vitest run server/utils/cade/__tests__/bizdevQueue.test.ts` exits 0
  prompt: |
    On approval, bizDev.buildDistribution (LinkedIn/X/email/keywords/backlinks) -> the existing
    marketing/outreach queue (reuse; do NOT build new). Test approved-article -> pack -> queue.

- id: cade-edge-report
  title: Edge Report - publish where the mispricing radar was later vindicated (embargoed)
  material: no
  model: sonnet
  depends: [cade-mispricing-radar, cade-publication-extract]
  proof: `npm run build` exits 0 AND `npx vitest run server/utils/cade/__tests__/edgeReport.test.ts` exits 0
  prompt: |
    server/utils/cade/edgeReport.ts: join radar divergences to later resolutions -> vindication
    rate -> claim-backed article via packages/cade-publication, GATED by the tiered gate
    (otc_price/financial) AND filtered through publishableEdges (embargo) so nothing publishes
    while a position is open/unresolved. Test vindication+tier+embargo. Recurring cron drafts.

OPERATOR:
  - Set MEDIUM_INTEGRATION_TOKEN + website base URL; deploy cade-publish-store migration after review. Publishing human-reviewed until CADE_PUBLISH_AUTONOMOUS=true.
