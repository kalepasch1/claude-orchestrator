# Operator Asks — Truth Ledger (2026-08-04)

Scope: every GENUINE operator (Kale) improvement request over ~120 days, deduplicated into programs per app, with on-repo truth status.

## Sources mined
- Mac: `intake/processed/` (423 briefs), `dropbox-PROMPT-*.md` drops (~90), `HOLD-PROMPT-*.md` (7), `MASTER-IMPLEMENTATION-RUNBOOK-2026-07-27.md`, `cowork-backlog/backlog.json` (operator-approved Cowork program), `dropbox-mission/`.
- DB (`tasks`): operator-origin asks are identifiable by `slug LIKE 'dropbox-%'` (intake-watcher decomposition of operator PROMPT drops; 985 tasks / 261 mission-groups in window). Machine-generated work uses prefixes `recover/improve/cont/canary/qafix/relfix/rework/...`.

## Truth methodology
- LANDED: key symbols/files exist on the repo default branch on the Mac.
- PARTIAL: some slices/symbols present, core deliverable absent.
- NEVER-LANDED: no code evidence AND DB slices pending/phantom/quarantined.
- UNKNOWN: could not cheaply verify.

## Headline findings
1. **PHANTOM epidemic**: a 2026-08-04 audit re-marked 10,572 tasks `PHANTOM_UNVERIFIED` ("marked MERGED but no shipped code found in target repo"). Nearly ALL July 8-15 operator missions (v4/v5/v6 waves, portfolio doctrine, filings-as-code, regulator empowerment, raise layer, mastery engine, life-goal stack) are phantom.
2. **DEPLOYED_AND_VERIFIED is ~only racefeed**: of 275 verified deploys in 120 days, ~270 are racefeed + 5 vigil. Zero for apparently, tomorrow, smarter, illuminati, pareto, apparently-law, hisanta, pmi.
3. **What actually shipped came from the Cowork-staged backlog** (`cowork-backlog/backlog.json`): the Tomorrow 5/95 + OTC program and the Apparently<->Tomorrow signal bridge are on default branches.
4. **The 2026-07-27 runbook waves (7 HOLD prompts) are mostly un-landed**: their late-July dropbox decompositions sit QUEUED/DECOMPOSED (pending), a handful of contract slices merged.

---

## APPARENTLY (`/Users/kpasch/Documents/apparently`, branch master, active thru 2026-08-04)

| Program | First asked | Status | Evidence / blocking |
|---|---|---|---|
| Tomorrow risk-signal bridge (contracts, HMAC client, outbox emitters) | Cowork backlog (Jul) | LANDED | `server/utils/tomorrow-client.ts`, `shared/contracts/tomorrow-signal.ts`, `server/engines/outbox/handlers/operational-risk-handler.ts` |
| Precedent indexing / precedent-gap | 2026-07-03 intake | LANDED | `server/utils/corpus-precedent.ts`, `server/utils/precedent-gap.ts` |
| Bespoke newsletter + gated report engine | 2026-07-30 (re-dropped 08-04) | PARTIAL | `server/engines/newsletter-generator.ts` exists; gated-report + shared contracts re-asked 08-04 (6 slices pending) |
| Vigil merge: gaming exams for all, omniscience corpus, lifecycle matrix, regulatory studio (HOLD-PROMPT-apparently-vigil-merge) | 2026-07-27/28 | PARTIAL (thin) | regulator-auth/portal-credential utils + `license-os/regulator-cooperation.ts` only; NO omniscience/exam-substrate code; 19/22 slices pending. Blocked on Wave-1 activation + fleet throughput |
| Consilium audit + conspicuous disclosure engine | 2026-07-29 (re-drop 08-04) | NEVER-LANDED | no `consilium` symbol; 6 slices pending |
| Capability OS (full smrter merge, per-user activation) | 2026-07-30 | NEVER-LANDED | no code; 10 slices pending |
| Full-picture ingestion push + review rooms | 2026-07-30 | NEVER-LANDED | no review-room code; 1/6 slice merged unverified |
| 1-click filing activation from risk gradient | 2026-07-30 | NEVER-LANDED | no code; 6 pending |
| Treasury tab (HOLD-PROMPT-apparently-treasury-tab, + pareto bridge) | 2026-07-27 | NEVER-LANDED | HOLD prompt never activated; no source symbols |
| Harvey parity (HOLD-PROMPT-apparently-harvey-parity) | 2026-07-27 | NEVER-LANDED | HOLD never activated |
| Coverage audit / universal coverage doctrine (HOLD + waveF) | 2026-07-27 / 08-02 | NEVER-LANDED | no code; waveF 6 pending |
| Filings-as-code / deadline omniscience / regulator dashboards | 2026-07-09 | NEVER-LANDED | 9/9 slices PHANTOM |
| R2f-R2k regulator empowerment layer | 2026-07-09 | NEVER-LANDED | 6/6 PHANTOM |
| Perpetual-spine bridges (apparently side) | 2026-08-02 | NEVER-LANDED | 24 slices queued |
| Cross-app hivemind federation | 2026-07-31 | PARTIAL | 1/5 merged unverified; no repo symbol found |
| Illuminati "trojun v2" vendor-agnostic compliance kernel | 2026-07-28 | PARTIAL | 2/37 merged, 25 pending, 9 quarantined |

## APPARENTLY-LAW (`/Users/kpasch/Documents/apparently-law`, branch main, 218 commits since Jun, active)

| Program | First asked | Status | Evidence / blocking |
|---|---|---|---|
| New site (Nuxt/Supabase/Vercel/Tailwind, first-party firm) | 2026-07-28 | PARTIAL | repo exists + builds + merges thru 08-04, but only 3 pages (`app/pages/{index,login,dashboard}.vue`). §2 prerequisite (repo/Vercel/Supabase) satisfied |
| Video education hub pipeline | 2026-07-30 | PARTIAL | `contracts/video-education-hub.js` only (contract slice); 7 slices pending |
| Expert network (HOLD-PROMPT-apparently-law-expert-network) | 2026-07-27 | NEVER-LANDED | HOLD never activated; no code |
| Beta readiness: token signup, legal doc set | 2026-07-29 | NEVER-LANDED | 7 slices pending; no signup surface beyond login |
| Launch QA full sweep (every page/API) | 2026-07-31 | NEVER-LANDED | 6 pending |
| UX consolidation / progressive disclosure / 1-click decisions | 2026-07-31 | NEVER-LANDED | 8 pending |
| Wave A: licensing pillar + approvals triage (revenue-critical) | 2026-08-02 | NEVER-LANDED | 4 pending |
| Wave B2: guidance corpus + ambiguity mining | 2026-08-02 | NEVER-LANDED | 5 pending |
| Doc-fabric bridge (Tomorrow prebuilt docs) | 2026-08-02 | PARTIAL | 1/4 merged unverified; no `docfabric` symbol in repo |

## TOMORROW (`/Users/kpasch/Documents/tomorrow/tomorrow`, branch main, 3157 commits since Jun, active)

| Program | First asked | Status | Evidence / blocking |
|---|---|---|---|
| Cowork 5/95 decision-budget program (FiveNinetyFive wrapper, trust ratchet, mandate collapse, war-room auto-skip) | Cowork backlog (Jul) | LANDED | `components/ui/FiveNinetyFive.vue`, `server/utils/ux/trustRatchet.ts`, `server/utils/warRoom/autoSkipGate.ts` |
| Cowork OTC program (perp lifecycle loop, composite payoff compiler, funding equilibrium, instrument discovery, mesh-of-rings, per-contract hedging) | Cowork backlog (Jul) | LANDED | `server/utils/otc/{compositePayoffCompiler,fundingEquilibrium,instrumentDiscovery,perContractHedger}.ts`, `otc/rings/meshOfRings.ts`, `otc/eventOptions/lifecycleManager.ts` |
| Cross-portfolio underwriting score + origination-embedded quoting | Cowork backlog (Jul) | NEVER-LANDED | `server/utils/risk/underwritingScore.ts` absent (server/utils/risk has completeness* only) |
| Self-service ECP / publish-to-mesh / individual path | 2026-07-28 | NEVER-LANDED | no publish-to-mesh symbol; 20 slices pending |
| Perpetual spine v1 (unified PTRRS fabric) | 2026-08-02 | NEVER-LANDED | no perpetualSpine symbol; 24 slices queued |
| Standby credit rail / retail pathway + credit rails v2 (HOLD-PROMPT-tomorrow-credit-rails-v2) | 2026-07-27 | PARTIAL | standby facility only in `server/utils/otc/stablecoinOverlay/facility.ts`; HOLD v2 never activated |
| Protocol credit primitive wave | 2026-08-02 | NEVER-LANDED | queued |
| Recycling / retention / reputation wave | 2026-08-02 | NEVER-LANDED | queued (6 under apparently project) |
| Scale wave: verticals, benchmark, policy | 2026-08-02 | NEVER-LANDED | queued |
| War-room anticipation fusion ("clairvoyant") | 2026-07-29 | PARTIAL | 1/8 merged unverified |
| Foulkon hedge bridge (TransferSpec population, 1-click) | 2026-07-30 | PARTIAL | 1/6 merged; illuminati `contracts/types/interfaces/hedge-bridge-DB-migration.ts` exists |
| Darwin kernel rollout (cross-product) | 2026-07-11 | PARTIAL | 5/47 merged, 40 PHANTOM; `otc/rings/darwinPassportBridge.ts` exists |
| Subscription simplification + insurance-elimination stack (v5/v6 waves) | 2026-07-09 | NEVER-LANDED | 20+24+18 slices PHANTOM |
| Strategy fixes 2026-08-01 | 2026-08-01 | UNKNOWN | no distinct DB mission traced |

## MADEUS / BEETHOVEN WEB (`/Users/kpasch/Documents/beethoven/claude-orchestrator`, branch master, active)

| Program | First asked | Status | Evidence / blocking |
|---|---|---|---|
| Review gate & steering, Wave 0 (staging->prod approval gate, waves dashboard, notifications, attribution) | 2026-07-27 (PROMPT ingested) | PARTIAL | preview gateway + audit landed (`web/server/api/previews/gateway/...`, `previews/audit.get.ts`); NO `steering_events` symbol; runbook says "verify before Wave 1" — this is the blocking gate for every Wave-1/2 program |
| Madeus platform (HOLD-PROMPT-beethoven-madeus-platform, Wave 2) | 2026-07-27 | PARTIAL | madeus traces in `web/app.vue` + composables (`usePreActionGuidance`, `useJourneyFriction`, `useAdaptiveProficiency`); HOLD never activated; blocked on Wave 0 |
| Merged-diff memory system | 2026-08-01 | PARTIAL | ~70 slices pending in DB, but `merged_diff_library.py` + `runner/test_merged_diff_memory_comprehensive.py` exist in live orchestrator |
| Approvals concierge (operator cards to Macey) | 2026-07-10 | NEVER-LANDED | no code; 7 slices phantom-era |
| Cross-app build progress console | 2026-07-30 | NEVER-LANDED | 6 slices pending |
| Legal radar v2 (all-app legal/compliance docs) | 2026-07-10 | PARTIAL | 4/25 merged, 20 PHANTOM; `dropbox-mission/legal-radar-v2/` spec remains |
| Economic scheduler (revenue-focused prioritization) | 2026-08-02 | NEVER-LANDED | 18 slices queued |
| Historical code recovery sweep | 2026-07-30 | PARTIAL | recovery-intent machinery visibly running fleet-wide; sweep mission 3 pending |

## VIGIL (`/Users/kpasch/Documents/vigil`, branch main, 194 commits since Jun, active)

| Program | First asked | Status | Evidence / blocking |
|---|---|---|---|
| Gaming regulator portal | 2026-07-30 | PARTIAL | `server/api/vigil/cooperation/change-notices.post.ts`, `platform.get.ts`; 5/6 DB slices pending |
| Foulkon enforcement bridge (EnforcementSpec) | 2026-07-30 | NEVER-LANDED | no foulkon code (aider history only); 6 pending |
| Universal exam substrate (waveE) | 2026-08-02 | NEVER-LANDED | no exam-substrate symbol; 6 pending under apparently |
| Full absorption into Apparently (runbook 4.4) | 2026-07-27 | NEVER-LANDED | vigil still a separate, actively-developed repo; apparently side has only trace refs. Blocking decision: operator must sequence the merge vs. continued parallel vigil development |
| Civic intelligence market (fleet-gen, verified) | Jul | LANDED | `improve-mesh-vigil-civic-intelligence-market` DEPLOYED_AND_VERIFIED 07-24 |

## SMARTER (`/Users/kpasch/Documents/smarter`, branch main, 959 commits since Jun, active)

| Program | First asked | Status | Evidence / blocking |
|---|---|---|---|
| War-room bridge to Tomorrow (live push/pull + remediation hook) | Cowork backlog (Jul) | LANDED | `server/api/warroom/bridge.post.ts`, `types/integration.ts` |
| Model-policy centralization | Cowork backlog (Jul) | LANDED | `server/utils/model-policy.ts` |
| Client portal & vault | 2026-07-05 intake | LANDED | `server/utils/clientPortalEngine.ts`, `careerVault.ts` |
| Embed & coordination (embeddable core, member identity, free-to-pickup, credits ledger, Pareto egress) | 2026-07-27/28 | PARTIAL | 1/8 merged; no member-identity or credits-ledger symbols; HOLD themes only partly staged |
| One-OS partner-level capability (for apparently-law) | 2026-07-29 (re-drop 08-03) | PARTIAL | `server/utils/capabilityContracts.ts` exists; 8 slices pending |
| Matter exhaust / shadow associate / counterparty scoring | 2026-07-09 | PARTIAL | `counterpartyDecisionTree.ts` exists; 8 slices PHANTOM |
| Raise: autonomous fundraising layer | 2026-07-09 | NEVER-LANDED | 9 slices PHANTOM; no code |
| v5 leave-timing optimizer + live-reg (sm-3/ap-6) | 2026-07-09 | NEVER-LANDED | 25 slices PHANTOM; no leaveTiming symbol |
| Email-into-smarter + secondary email | 2026-07-03 | UNKNOWN | not cheaply verifiable |
| Comms OS / comms intel | 2026-06-29/30 | UNKNOWN | not cheaply verifiable |

## ILLUMINATI (`/Users/kpasch/Documents/illuminati`, branch master, only 60 commits since Jun — least-served repo)

| Program | First asked | Status | Evidence / blocking |
|---|---|---|---|
| Overlay & trust (trust floor, 5 install surfaces incl. gateway proxy, live sidecar, option ladder, receipt packs, living policies) — HOLD Wave 1 | 2026-07-27 | NEVER-LANDED | no trustFloor/sidecar/gateway-proxy symbols; HOLD decomposition pending |
| Foulkon decision instrument (full implementation) | 2026-07-30 | PARTIAL | contracts only: `contracts/types/interfaces/{DB-migration,hedge-bridge-DB-migration}.ts`; 5 groups pending |
| One-app unification with Apparently (capability surface) | 2026-07-29 | NEVER-LANDED | 1/14 merged unverified; 13 pending |
| Precedent graph compression (zero-token reasoning) | 2026-07-31 | PARTIAL | `server/utils/precedentCitationGraph.ts` exists; 7 slices pending |
| Latency-hiding decision DAG + gradient displays | 2026-07-31 | NEVER-LANDED | no code; 5 pending |
| Wave B1: Foulkon darwinian hive (jurisdictional competence) | 2026-08-02 | NEVER-LANDED | 6 pending |
| Cross-app hivemind federation (illuminati side) | 2026-07-31 | NEVER-LANDED | 4 pending |

## PARETO-2080 (`/Users/kpasch/Documents/pareto/2080`, branch main, 943 commits since Jun, active)

| Program | First asked | Status | Evidence / blocking |
|---|---|---|---|
| Luxury ECP exchange / consigliere repositioning ($5M passport) — HOLD Wave 2 | 2026-07-27/28 | NEVER-LANDED | no ECP/luxury-exchange source symbols (matches only in built `.vercel/output` bundles); 9 slices pending; depends on Tomorrow standby S2S (Wave 1, un-landed) |
| Treasury bridge to Apparently (HOLD-PROMPT-pareto-apparently-treasury) | 2026-07-27 | NEVER-LANDED | treasury only in `server/utils/_dormant/`; HOLD never activated |
| Life-goal autonomy stack (v2) | 2026-07-09 | PARTIAL | life pages/assets exist; 9 slices PHANTOM — pre-existing life features, autonomy stack unproven |
| Track-record surfaces | 2026-07-13 | NEVER-LANDED | no trackrecord symbol (racefeed got its trackrecord screen instead) |
| Tax-child, posture-and-proofs, frontier/levers waves | 2026-06-30/07-05 | UNKNOWN | intake briefs decomposed into phantom-era batches; no cheap symbol check |
| Concierge (personal) | earlier | LANDED | `server/api/personal/concierge.*` (predates window; noted for context) |

## HISANTA / SANTAS-SECRET-WORKSHOP (`/Users/kpasch/Documents/hisanta`, branch master, 1053 commits since Jun, active)

| Program | First asked | Status | Evidence / blocking |
|---|---|---|---|
| Mastery engine / learning ladder | 2026-07-09 | LANDED | `app/(workshop)/learning-ladder.tsx`, `lib/learning.ts` + tests |
| Premium pricing / earnable-free (advent pass) | 2026-07-28 | PARTIAL | `app/(workshop)/advent-pass.tsx`, family-month pricing; 1/3 merged, 2 pending |
| Family v2 / grandma rail / gifting | 2026-07-09 | PARTIAL | family surfaces + grandma refs in components/tests; original mission PHANTOM |
| Multiplayer longitudinal | 2026-06-29 | NEVER-LANDED | no multiplayer symbol |

## RACEFEED / GALOP (`/Users/kpasch/Documents/galop/racefeed`, branch master, active)

| Program | First asked | Status | Evidence / blocking |
|---|---|---|---|
| Engagement stack: card mode, multi-race betting, paid play | 2026-07-09 | LANDED | 14 slices DEPLOYED_AND_VERIFIED (the ONLY operator mission fully verified-deployed fleet-wide); trackrecord screen + race predictor deployed 07-22 |
| Free-play launch (cross-brand with apparently) | 2026-07-28/30 | PARTIAL | freePlay in `components/WebDashboard.tsx`; cross-brand groups pending |
| Experience v2/v3, social AI, surfaces economy, launch security/brand/feeds | 2026-06-29 | UNKNOWN | intake briefs; no distinct DB missions traced |

## PMI / ADVISORS (`/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi`, branch main, 38 commits since Jun)

| Program | First asked | Status | Evidence / blocking |
|---|---|---|---|
| Think-tank launch (brand, exam, apparatus) | 2026-07-28 | NEVER-LANDED | only `.recovery-intent-*` breadcrumbs in repo; 7 slices pending |
| PMA credential + Publius engine | 2026-07-29 | NEVER-LANDED | no publius symbol; 3 pending |

## KALEPASCH.COM (`/Users/kpasch/Documents/smarter/pasch`, active)

| Program | First asked | Status | Evidence / blocking |
|---|---|---|---|
| (maintenance only: weekly lint, qafix, reusable-diff inventory) | ongoing | LANDED | merges thru 2026-08-04; no distinct operator feature programs in window |

---

## Cross-cutting blocking decisions (operator-owned, from MASTER runbook §2/§3)
1. **Wave 0 review gate is the chokepoint**: `steering_events`/notifications not verified in beethoven web — runbook forbids Wave 1/2 promotion until it works. Most NEVER-LANDED items above are queued behind it.
2. **HOLD prompts never renamed to PROMPT-***: apparently-treasury-tab, apparently-harvey-parity, apparently-coverage-audit, apparently-law-expert-network, tomorrow-credit-rails-v2, beethoven-madeus-platform, pareto-apparently-treasury (activation = rename at orchestrator root).
3. **S2S secrets not provisioned** (`APPARENTLY_LAW_SHARED_SECRET`, `WARROOM_S2S_SECRET`, `PARETO_SMARTER_SHARED_SECRET`, `ILLUMINATI_API_KEY/URL`) — blocks bridges even where code lands.
4. **Merge-train throughput / phantom-merge integrity**: the 08-04 audit found ~10.5k "merged" tasks with no shipped code; until branch-loss + stub-merge root cause (dropbox 08-02 pipeline-recovery mission, pending) is fixed, new decompositions will keep evaporating.
5. **Vigil-into-Apparently absorption**: signed off 07-27 but both repos still diverge daily — needs an explicit sequencing decision.

## Per-app tallies (operator programs only)
| App | Landed | Partial | Never | Unknown |
|---|---|---|---|---|
| apparently | 2 | 4 | 9 | 0 |
| apparently-law | 0 | 3 | 6 | 0 |
| tomorrow | 2 | 5 | 6 | 1 |
| madeus/beethoven | 0 | 5 | 3 | 0 |
| vigil | 1 | 1 | 3 | 0 |
| smarter | 3 | 3 | 2 | 2 |
| illuminati | 0 | 2 | 5 | 0 |
| pareto-2080 | 1 | 1 | 3 | 1 |
| hisanta | 1 | 2 | 1 | 0 |
| racefeed/galop | 1 | 1 | 0 | 1 |
| pmi | 0 | 0 | 2 | 0 |
| kalepasch.com | 1 | 0 | 0 | 0 |

*Generated 2026-08-04 by portfolio truth-ledger sweep (intake + dropbox drops + HOLD prompts + cowork backlog + orchestrator DB + on-repo symbol checks).*
