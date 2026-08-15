# P0 — FIRST-REAL-USER BLOCKERS (audit-confirmed 2026-07-31, file-cited). HIGHEST PRIORITY.
# Nothing else ships until these land. Each numbered item is one mergeable shard.

## ===== APPARENTLY (project: apparently) =====
A1. WRITE `application_requirements` (THE root break). On application creation, expand the
    already-seeded catalog `license_application_requirements` into per-application rows.
    Today: 5 readers, ZERO writers -> checklist permanently empty, completion % always 0,
    cover-letter doc list always generic, and `pages/applications/[id]/submission.vue:26-30`
    "all requirements complete" gate CAN NEVER PASS. Files: server/api/smart-intake/
    create-applications.post.ts, app/stores/applications.ts:81.
A2. FIX `applications.status` CHECK violations — 2 of 3 creation paths 500 today:
    create-applications.post.ts:63 uses 'intake' (not in the CHECK from 001_initial_schema.sql:
    88-92); ops/admin/client-workups/[id]/provision.post.ts:229-230 uses 'pending' AND writes
    priority:'high' into an INTEGER column. Either widen the constraint or use legal values.
A3. WRITE `application_documents`. 6 readers, ZERO writers. Add "attach dataroom document to
    requirement" so packets/review/deficiency responses can reference real files.
A4. RENDER REAL BYTES. server/engines/submission-assembler.ts builds filenames + /tmp paths and
    hashes a JSON manifest; no renderer exists ("downstream skills" are absent) and /tmp is
    ephemeral on Vercel. Emit cover letter DOCX + filled form PDFs + exhibit binder into Supabase
    Storage. Deps already present (docx, pdf-lib, pdfkit, exceljs); missing piece is per-
    jurisdiction field mapping -> pdf-lib form.getTextField().setText().
A5. MAKE ONE SUBMISSION MODALITY REAL. server/engines/autofill-pipeline.ts:532-678 is the only
    "submit" and every branch is a no-op (email branch returns success WITHOUT SENDING;
    mail branch returns an unused label object; portal branch returns success:false with a
    message claiming automation started). Honest MVP: rendered packet + jurisdiction-specific
    portal/mail instructions from the curated routes already in server/engines/submission-
    router.ts, and ACTUALLY send for method:'email'. DO NOT ship browser automation: playwright
    is a devDependency and will not exist in the Vercel bundle.
A6. FIX THE ASSEMBLE GATE: server/api/submissions/[id]/assemble.post.ts:40 requires
    preflight_status==='ready' but pass-preflight.ts:325 writes 'passed'/'blocked' and the CHECK
    (069_autonomy_scaffolding.sql:35) forbids 'ready' -> 409 in 100% of cases. Then give it a UI.
A7. EXPOSE THE ATTORNEY SIGN-OFF GATE: applications/[id]/final-review.post.ts is orphaned; wire
    it into applications/[id]/submission.vue as a HARD gate before "Record Submission".
A8. BILLING INTEGRITY: add subscription_data:{metadata:{plan_id,tier,organization_id}} to
    server/api/billing/checkout-session.post.ts (Stripe does NOT copy session metadata to the
    Subscription) — without it `org_subscriptions` is never written and every paying customer
    has empty entitlements. Then WIRE server/utils/subscription-gate.ts requireSubscription()
    (currently ZERO importers) into licensing/filing routes and increment subscription_usage.
    DELETE-or-complete server/api/payments/webhook.post.ts (live signature-verifying endpoint
    whose handlers are all commented-out no-ops).
A9. SECURITY: server/api/documents/upload.post.ts has NO auth check and accepts caller-supplied
    bucket + path. Gate it now.
A10. KEY-PERSON + EXAM ENTRY POINTS: add the missing /api/intake/submit (stakeholder.vue:503
    404s today); replace the fully-hardcoded app/pages/dashboard/key-persons/index.vue with real
    queries; give /api/nfa/fingerprint/request a UI so filing_fingerprint_requests is populated
    (its cron polls an empty table); connect at least one of exam-preparation.ts /
    regulator-readiness-scorer.ts / automated-evidence-compiler.ts (ALL have zero importers) to a
    route + page + schedule — Chain 3 currently has NO entry point at all.
A11. DATA-MODEL COLLAPSE (design decision, then migrate): four disjoint models for the same
    concept — applications/*, engagements+managed_filings, submissions/*, filings. /client/* and
    /applications/* show different records to the same customer. Pick one, migrate the rest.

## ===== TOMORROW (project: tomorrow) =====
T1. CREATE A `SwapOrganization` for every new user (at signup or application approval). Nothing
    creates one today, so server/api/exposures/index.post.ts 404s at line 30 and NO user can
    register a single exposure. Root blocker for the entire chain.
T2. WRITE THE ~29 MISSING AUTO-IMPORTED COMPOSABLES (~80 call sites; absent from
    .nuxt/imports.d.ts so the build passes and pages throw at runtime). Start: useExposures (7
    pages), useExchangeMeta (17), useConfirm (12), useBadges (6), useVerificationGate (5).
    ADD A CI GATE diffing auto-import call sites against .nuxt/imports.d.ts.
T3. PERSIST DOCUMENT UPLOADS: server/api/hedging/upload.post.ts extracts exposures then returns
    WITHOUT ANY prisma.create — data is discarded and the UI navigates to an empty page.
T4. MAKE RECOMMENDATIONS EXIST: nothing ever writes HedgingRecommendation2 (3 readers, 0
    writers) and the v1 writer lives in a Nitro plugin gated off in serverless. Either repoint
    the API at hedgeRecommendation or generate v2 rows — and give generation a CRON, because
    contractSyncScheduler never runs on Vercel.
T5. REPLACE THE SIMULATED FILL: server/utils/hedgeExecutor.ts:158 self-fills with no
    counterparty. Route to real bilateral matching (bot137 Trade path); wire the orphaned
    server/api/otc/docs/generate-confirmation.post.ts into post-trade UI; build /api/hedges/close
    (pages/app/hedges/execute.vue:865 calls a route that doesn't exist).
T6. UNIFY THE THREE IOI STORES (OrderBookEntry / IndicationOfInterest / KV standing book) or at
    minimum surface /api/otc/orders/user on the dashboard so mandate-authorized auto-IOIs are
    visible to the user who authorized them.
T7. MIGRATE THE 10 DEV-ONLY NITRO PLUGINS TO CRONS — especially conditionalIoiScheduler and
    positionDriftScheduler (load-bearing for "always-on"; no cron calls runConditionalIoiExecutor
    or runDriftController today).
T8. WIRE THE 6 ORPHANED NOTIFIERS (notifyTradeMatched, notifySignatureComplete, notifySettlement,
    notifyPositionExpiry, checkBeneficialHedges, sendDailyDigest — all zero callers) and confirm
    EMAIL_SENDING_ENABLED=true in Vercel prod.
T9. ADMIN REVIEW UI for /api/admin/applications/[id]/review — applications pile up unreviewable.
T10. FOULKON HEDGE BRIDGE: build inbound POST /api/apparently/foulkon/hedge-quote consuming
    HedgeQuoteRequest from illuminati/server/utils/hedgeBridge.ts (whose only importer today is
    its own test) + the gradient_hedge_activations migration — or mark the bridge not-shipped.
    Posture: bilateral ECP parametric swaps, no insurance framing, no click-to-execute.
T11. Fix the 11 UI->missing-route calls (hedges/close, autopilot/generate-ioi, hedge/positions,
    firm/rooms/amendment/*, otc/bank/profile, user/risk-settings, hive/market-data/overview,
    admin/export, admin/broadcast, terminal/execute, exposures/indirect).

## ===== PARETO-2080 (project: pareto-2080) =====
P1. CREATE THE `Profiles` ROW ON FIRST LOGIN — zero create/upsert exists anywhere (43 findUnique,
    10 update, 0 create) and no auth trigger. server/api/users/me.get.js:15 throws 404 for every
    real new user, so ~40 dashboard fetches never fire. Note schema requires firstName/lastName/
    email/password/birthday (prisma/schema.prisma:1078-1082) — relax to nullable or supply
    defaults. NOTHING in the app works until this exists.
P2. ROUTE NEW USERS THROUGH ONBOARDING: pages/Onboarding/[userId].vue (530 lines) is orphaned;
    pages/confirm.vue:41 should send profile-less users there before /deathTimer.
P3. BUILD OR REMOVE the 7 missing /api/personal/* endpoints (autonomous-feed + 6 sub-actions,
    platform-metrics, trust-score, negotiation-memory, financial-heartbeat, value-projection,
    household-value) — ~5 dashboard panels render blank forever.
P4. BILLING FROM SCRATCH if monetization is required at launch — there is NO Stripe anywhere
    (no dep, no routes, no env, no subscription model). Price IDs were provisioned in Stripe
    (Pareto Plus monthly/annual) and set in Vercel; the app side does not exist.
P5. DELETE/REPAIR pages/Create.vue (supaAuth boilerplate that signs users up WITHOUT a profile)
    and pages/User/[userId]/Account.vue (queries a lowercase `profiles` table with columns that
    don't exist; would also be RLS-blocked).
P6. LAND RLS POLICIES AS MIGRATIONS so scripts/check-rls.mjs has something to gate on (the
    lockdown was applied out-of-band; zero ENABLE ROW LEVEL SECURITY in supabase/migrations), and
    schedule the two unscheduled crons (commitment-sweep, treasury-ledger).

## BINDING
Fix root causes, not symptoms. Every fix ships with a test. Coverage doctrine applies: any new
sweep/scan declares its universe and names what it did not reach. No insurance framing anywhere.
Release windows govern prod promotion. Commits kalepasch1 <kalepasch@gmail.com>.
