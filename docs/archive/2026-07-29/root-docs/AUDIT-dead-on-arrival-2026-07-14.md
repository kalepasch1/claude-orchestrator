# Cross-App "Landed but Not Wired" Audit

**Date:** 2026-07-14  
**Scope:** All connected app folders  
**Mode:** Read-only (search + report)

---

## Executive Summary

| App | Total logic modules | Wired | Dead-on-arrival | Test-only | Barrel-only |
|---|---|---|---|---|---|
| pareto/2080 | 175 | 145 | 1 | 29 | 0 |
| apparently | 149 utils + 70 engine subdirs | ~135 utils + ~60 engine subdirs | ~14 utils + 10 engine subdirs | 2 utils | 4 stale barrels |
| smarter | 129 | 127 | 2 | 0 | 0 |
| darwn | 10 | 9 | 1 | 0 | 0 |
| hisanta | 14 | 13 | 1 | 0 | 0 |
| Sustainable_Barks | 2 | 2 | 0 | 0 | 0 |
| claude-orchestrator | 445 runner modules | 275 imported + 117 standalone | 48 true dead (not imported, no entrypoint) | 5 | n/a |

**Total dead-on-arrival modules across all apps: ~77 + 10 dead engine subdirs**

---

## 1. pareto/2080 (Personal Finance App)

**175 server/utils modules scanned**

### Dead-on-Arrival (1 module, zero references anywhere)

| Module | Purpose | Nearest missing wire |
|---|---|---|
| `bookingProviders.js` | Booking provider integrations (hotel/flight/car stubs) | Needs `POST /api/finance/bookings/providers` |

### Test-Only (29 modules — have tests but no production import path)

**Cluster: RFQ / Auction / Market-Making (10 modules, ~895 lines)**

| Module | Purpose | Nearest missing wire |
|---|---|---|
| `rfqMesh.js` | Continuous swarm RFQs + cohort bargaining | `POST /api/finance/rfq` |
| `rfqTargeting.js` | Target RFQs to best-fit providers | Called by rfqMesh |
| `standingAuction.js` | Rolling cohort auction | Auction API surface |
| `reverseAuction.js` | Decentralized reverse auction | Auction API surface |
| `demandAuction.js` | Two-sided provider-bids-for-volume | Auction API surface |
| `afterTaxNormalize.js` | After-tax rate normalization | Consumed by auction engines |
| `providerElasticity.js` | Learn provider price floors | Consumed by auction engines |
| `recordMarketOutcome.js` | Data-flywheel write-back | Consumed by auction engines |
| `savingsIndex.js` | Anonymized public proof of savings | `GET /api/public/savings-index` |
| `negotiationFanout.js` | Parallel multi-provider negotiation | Negotiation API route |

**Cluster: Staged-Action / Bundle / Wallet (5 modules, ~485 lines)**

| Module | Purpose | Nearest missing wire |
|---|---|---|
| `sessionRail.js` | Staged-action lifecycle | Middleware or API integration |
| `bundleCommit.js` | One-tap correlated batch commit | Approval-flow integration |
| `crossDomainStaging.js` | Cross-domain joint staging | Approval-flow integration |
| `syntheticBundle.js` | Manufacture best-of-breed offers | Bundle API route |
| `walletBundle.js` | Relationship-level mega-cohort | Wallet API route |

**Cluster: Forward Demand / Application Pipeline (3 modules, ~301 lines)**

| Module | Purpose | Nearest missing wire |
|---|---|---|
| `applicationFlow.js` | Turn optimized rate into one-tap application | `POST /api/finance/apply` |
| `forwardDemand.js` | Time-arbitrage forecasted demand | Demand-signal API |
| `prequalification.js` | Soft pre-qualification | Pre-qual API route |

**Standalone dead engines (11 modules)**

| Module | Purpose | Nearest missing wire |
|---|---|---|
| `intakeExtraction.js` | Extract structured data from intake documents | `POST /api/finance/intake` |
| `depositBonusCrawl.js` | Crawl/normalize deposit bonus offers | Cron job in `server/tasks/` |
| `macroTiming.js` | Compose prediction signals + calendar effects | Feed `/api/personal/treasury` |
| `antiDetection.js` | Keep cohort RFQs looking organic | Consumed by rfqMesh |
| `trustAutotune.js` | Self-calibrating autonomy thresholds | Feed `/api/approvals` |
| `simHarness.js` | Whole-system simulation harness | Diagnostic/operator endpoint |
| `regretEngine.js` | Quantified cost-of-inaction nudge | Feed deathTimer or approvals |
| `claimsMaximizer.js` | Insurance claims maximization | `GET /api/personal/insurance/claims` (out-of-scope per CLAUDE.md) |
| `darwinCapabilities.js` | Cross-product capability publishing | Capability registry endpoint |
| `fairDivision.js` | Fair cost/surplus splitting for coalitions | Feed groupBuying or planning-room |
| `posInterceptor.js` | Point-of-sale decision interceptor | Out of scope per CLAUDE.md |

**Unreachable subsystem: `server/utils/cade/` (6 files)** — entire directory unreferenced by any wired code.

### Top 5 Fixes — pareto/2080

1. **`regretEngine.js`** — Behavioral nudge showing cost-of-inaction. Wire into "Needs You" inbox cards on deathTimer.
2. **`macroTiming.js`** — Timing-aware recommendations. Compose into `/api/personal/treasury` or investment recs.
3. **`fairDivision.js`** — Equitable cost splitting. Wire into `/api/personal/groups/pools` or `/api/planning-room`.
4. **`trustAutotune.js`** — Self-calibrating autonomy. Integrate into approval policy evaluation.
5. **`depositBonusCrawl.js`** — Bonus offer crawler. Register as cron job feeding `depositBonusData.js`.

---

## 2. apparently (Licensing/Legal/Regulatory Platform)

**149 server/utils + ~70 engine subdirectories scanned**

### Dead Engine Subdirectories (10 subdirs, 24 files total)

These engine subdirectories exist on disk but are never imported by any API route, page, component, util, task, plugin, or middleware:

| Subdirectory | Files | Purpose (inferred) | Notes |
|---|---|---|---|
| `shared/` | 6 | Shared engine utilities | `citations/` imports from it, but `citations/` is itself dead |
| `nfa-optimization/` | 3 | NFA filing optimization | No API surface |
| `fees/` | 3 | Fee calculation | Referenced by `competitive-moat-strategy.ts` engine only |
| `cache/` | 2 | Engine caching layer | No consumers |
| `formation-optimization/` | 2 | Entity formation optimization | No API surface |
| `knowledge-graph/` | 2 | Knowledge graph engine | Referenced by `hive/regime-diffusion.ts` only |
| `legal-opinions-optimization/` | 2 | Legal opinion optimization | No API surface |
| `citations/` | 2 | Citation management | Only imports from dead `shared/` |
| `cepl/` | 1 | Unknown | No references |
| `ploeh/` | 1 | Unknown | No references |

### Dead server/utils (14 modules — never imported by any reachable surface)

| Module | Key exports | Nearest missing wire |
|---|---|---|
| `activity-feed.ts` | `ActivityAction`, `ActivityEvent` | Needs activity-feed API route or page widget |
| `address-validation.ts` | `validateAddress()` | Needs integration into entity/onboarding forms |
| `api-response.ts` | `apiSuccess()`, `apiError()` | Should be used by API routes (or remove if superseded) |
| `api-version.ts` | API versioning utilities | Should be used in middleware |
| `congress-api.ts` | Congressional bill search | Needs regulatory intel API surface |
| `cftc-api.ts` | CFTC report/enforcement fetching | Needs CFTC monitoring endpoint |
| `date-helpers.ts` | `parseDateUTC()`, `addDaysUTC()` | Should be used by engines needing date math |
| `db.ts` | `repo()`, `repos` typed DB access | Should replace raw Supabase calls |
| `documentExtractor.ts` | `DocumentType` enum, tax/articles extraction | Needs document processing pipeline |
| `pay-gov.ts` | `PaymentRequest`, `PaymentResult` | Needs payment processing endpoint |
| `pdf-diff.ts` | `comparePdfVersions()` | Needs document comparison API |
| `phdFormDiffer.ts` | `diffForms()`, `formatDiffReport()` | Needs form-diff page or API |
| `portal-credential-cipher.ts` | `encryptPortalCredential()` | Only used by `scripts/rotate-portal-cipher-key.ts` |
| `file-storage.ts` + `virus-scanner.ts` | File upload + virus scanning | Both dead; file-storage imports virus-scanner but nothing imports file-storage |

### Stale Barrels (4 engine index.ts files missing sibling exports)

| Barrel | Missing exports |
|---|---|
| `server/engines/rewards/index.ts` | `compliance-gamification`, `kill-switch`, `s2s` |
| `server/engines/platform-core/index.ts` | `approval-probability`, `canonical-field-registry`, `cross-activation-scanner`, `cross-sell-router`, `digital-twin`, `effort-estimator`, `next-best-action`, `outcome-flywheel`, `personalized-reg-feed`, `premium-assist-ladder` (10 missing!) |
| `server/engines/regulator-intel/index.ts` | `labels`, `multi-jurisdiction-assembler`, `portal-monitor`, `temporal-state` |
| `server/engines/gaming-enablement/index.ts` | `support-entity-exposure`, `sweeps-regime-classifier` |

The `platform-core` barrel is the worst offender — 10 sibling modules exist but aren't exported. Any code importing from the barrel won't see them.

### Top 5 Fixes — apparently

1. **`platform-core/index.ts` barrel** — 10 missing exports. Any engine importing `from '../platform-core'` silently gets nothing for these modules. Add the re-exports.
2. **`file-storage.ts` + `virus-scanner.ts`** — Complete file-upload pipeline sitting unused. Wire into document upload endpoints.
3. **`db.ts` repo pattern** — Typed DB access layer that nothing uses. Adopt in new API routes to replace raw Supabase calls.
4. **`congress-api.ts` + `cftc-api.ts`** — Government data fetchers. Wire into regulatory-intel endpoints.
5. **`rewards/index.ts` barrel** — Missing `kill-switch` export means the rewards kill-switch engine can't be reached through the barrel.

---

## 3. smarter (Legal Practice Management)

**129 server/utils modules scanned**

### Classification

| Status | Count |
|---|---|
| Wired (direct or transitive) | 127 |
| Dead-on-arrival | 2 |

### Dead-on-Arrival (2 modules)

| Module | Purpose | Notes |
|---|---|---|
| `filingWorkflowSupport.ts` | Filing checklist/workflow types | No imports anywhere — not even by other utils or tests |
| `socialTick.ts` | Social media post publishing | No imports, no tests. `social.ts` (the platform config) IS transitively wired via `etiquette.ts` |

### Top Fix — smarter

1. **`socialTick.ts`** — The social posting engine. `social.ts` (platform config) is wired, but the actual publishing logic (`socialTick`) never got connected. Wire into a cron or the social API surface.

---

## 4. darwn (Healthcare Worker Trading Platform)

**10 server/utils modules scanned**

### Dead-on-Arrival (1 module)

| Module | Purpose | Notes |
|---|---|---|
| `orderMatcher.ts` | Order matching engine | `orderBook.ts` IS wired but `orderMatcher` is not imported by anything. Likely superseded by `attorneyOrderMatcher.ts`. |

---

## 5. hisanta (Santa's Secret Workshop)

**14 lib/ modules scanned**

### Dead-on-Arrival (1 module)

| Module | Purpose | Notes |
|---|---|---|
| `streams.ts` | Streaming/real-time functionality | Not imported by any page, component, or hook |

---

## 6. Sustainable_Barks

**2 server/utils modules — both wired. No dead code.**

---

## 7. claude-orchestrator (Fleet Runner)

**445 runner/*.py modules scanned**

### Classification

| Status | Count |
|---|---|
| Imported by other modules | 275 |
| Standalone scripts (`if __name__`) | 117 |
| True dead (never imported, no entrypoint) | 48 |
| Test files | 5 |

### True Dead Modules (48 — never imported, no `if __name__` block)

These are library modules that nothing imports:

| Module | Likely purpose |
|---|---|
| `bandit` | Multi-armed bandit for experiment selection |
| `barks_esg` | ESG scoring for Sustainable Barks |
| `barks_grants` | Grant matching for Sustainable Barks |
| `bot_factory` | Bot creation/templating |
| `branch_fleet_recovery` | Fleet recovery from branch failures |
| `build_cache` | Build artifact caching |
| `bundle_handoff` | Bundle handoff between stages |
| `cade_scorecard` | CADE performance scoring |
| `claim_affinity` | Task-to-agent affinity matching |
| `committee_bypass` | Approval committee bypass logic |
| `config_sync` | Config synchronization across fleet |
| `contract_drift` | Contract drift detection |
| `crud` | Generic CRUD operations |
| `cx_confidence_gap_learning` | CX confidence gap analysis |
| `cx_owner_language_tuning` | CX owner language optimization |
| `cx_tribunal_model` | CX tribunal decision model |
| `dag_validator` | DAG validation |
| `dependency_aware_release` | Dependency-aware release ordering |
| `dynamic_tier_marginal_quality` | Dynamic quality tiering |
| `error_classifier` | Error classification |
| `experiment_router` | Experiment routing |
| `feature_map` | Feature mapping |
| `merge_invariant_firewall` | Merge invariant enforcement |
| `merge_test_gate` | Merge test gating |
| `mesh_optimizer` | Service mesh optimization |
| `ml_task_router` | ML-based task routing |
| `post_merge_smoke` | Post-merge smoke testing |
| `pr_integrate` | PR integration |
| `preview_deploy` | Preview deployment |
| `preview_promote` | Preview promotion |
| `preview_promoter` | Preview promotion logic |
| `prompt_distiller` | Prompt distillation |
| `provenance` | Provenance tracking |
| `providers` | Provider management |
| `ratio_cap` | Ratio capping |
| `realtime_config` | Real-time config updates |
| `reset_scheduler` | Reset scheduling |
| `rootcause_cluster` | Root cause clustering |
| `scoreboard_data` | Scoreboard data |
| `scoring` | General scoring |
| `self_authored_capabilities` | Self-authored capability discovery |
| `social_gap_intake` | Social gap analysis intake |
| `speculative_exec` | Speculative execution |
| `speculative_parallel` | Speculative parallel execution |
| `speculative_premerge` | Speculative pre-merge |
| `targeted_remedy` | Targeted remediation |
| `tests_first_gate` | Tests-first gating |
| `value_router` | Value-based routing |

### Top 5 Fixes — claude-orchestrator

1. **`error_classifier`** — Error classification for the fleet. Should be imported by `action_runner` or `auto_remediate`.
2. **`dag_validator`** — DAG validation. Should be called by `planner.py` before executing task graphs.
3. **`merge_test_gate` + `merge_invariant_firewall`** — Merge safety checks. Should be wired into the merge pipeline.
4. **`config_sync`** — Fleet config sync. Should be called by `fleet_control.py` (which uses `fleet_config` table per CLAUDE.md).
5. **`prompt_distiller`** — Prompt optimization. Should feed into `prompt_factory.py`.

---

## Cross-App Patterns

### Why this keeps happening

The pattern is consistent across all apps: engine/logic files are authored (or merged by automation) separately from their API routes, pages, and registry entries. The three highest-signal tells confirmed:

1. **`server/utils` module with zero `server/api` + `pages` references** — pareto/2080 (29 modules), apparently (14 modules), smarter (2 modules)
2. **Barrel `index.ts` missing sibling exports** — apparently has 4 stale barrels, with `platform-core` missing 10 of its siblings
3. **Standalone runner modules with no caller** — claude-orchestrator has 48 library modules that nothing imports

### The "engine-first, wire-later" anti-pattern

Every app shows the same workflow: build the engine → write tests → commit → never wire the route/page/registry. The test suite passes (the engine works in isolation), so CI is green, but the feature is unreachable. pareto/2080 is the clearest case: 29 of 30 dead modules have passing tests.

---

Reply `wire <app> <module>` and I'll add the minimal route/page/barrel/registry entry to make it reachable, with a test.
