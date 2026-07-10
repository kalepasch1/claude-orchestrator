# Portfolio doctrine + shared services (X-items, O-items, P0)

Target repos: claude-orchestrator (packages/darwin-kernel + shared services) with adoption tasks fanned out per app repo.
Source specs: REVIEW v1 §0/§9, v2 §8, v3 §8. Depends on queued G1–G21, H1–H4 (kernel), I1–I3. O4 (doctrine propagation) should be built FIRST and then used to fan out P0 adoption.

## Objectives

1. **P0-DOCTRINE portfolio decision budgets** — one Decision Budget spec + lint (generalize lint-decision-budgets.mjs from B5) adopted by every app; core journeys ≤3 decisions, trust-ratchet graduation toward 1. 
2. **O4 Doctrine propagation as first-class intake** — proven doctrine in one repo auto-generates adoption tasks for others via prompt_factory; P0-DOCTRINE is the first test case. Proof: pytest on propagation output.
3. **P0-PASSPORT cross-product passport wallet** — unified surface over B3/E1/F2 claims; "you're already done" first-screen moment per product. 
4. **P0-RECEIPTS consumer explanation surface** — one card per autonomous action: what/why/counterfactual cost/undo; shared component consumed by all apps.
5. **X1 Autonomy Console for end users** — consumer-ized I1: per-user view of bot actions, receipts, pause button, authority slider; shared service + per-app embed.
6. **X2 Shared Regime-Change Oracle + connector layer** [MATERIAL] — ONE kernel service: court dockets, legislative APIs, agency registers, gazette feeds → quorum determinations via multi-source validator pattern, signed contestable receipts. Consumers: Tomorrow T4v2 settlement, Apparently A1 diff-watch, Pareto P4v2, Smarter practice alerts. Plus one shared connector framework (ERP/loan-tape pipes for T7v3, GitHub/data-pipeline webhooks for A7) — build once. HIGHEST PRIORITY in this prompt: unblocks four apps. Proof: oracle determinism/quorum tests; connector contract tests.
7. **X4 Cross-app credibility currency** — standardize verified-predictive-credibility as a kernel claim type (Triage staking scores, Smarter telemetry scores, Galop calibration, Tomorrow reputation → one primitive; extends passports). Proof: claim mint/port tests across two fixture apps.
8. **X5 Internal regime prediction markets** — fleet bots + opted-in users forecast regime events; calibration prices T4v2 external swaps; reuse Galop scoring stack. Proof: market → pricing pipeline test.
9. **N7 Receipts API platform** — grow G2 verifier into public third-party verification API (avoided losses, filing status, placement guarantees, savings). Proof: external-verification contract tests.
10. **O1 Pattern registry with metered rebates** [MATERIAL] — signed registry entries from auto-extracted merge patterns (G12 signing); IP/privacy scrubbing gate at publication (process patterns only) built FIRST; usage metering + rebate ledger crediting originating projects. Proof: scrub-gate fail-closed test; metering test.
11. **O2 Cross-app golden-journey regression suite** — portfolio-level journeys (Tomorrow onboard → passport → Galop KYC → Pareto underwrite) run on every material merge anywhere. Proof: suite runs in CI; injected cross-app break caught.
12. **O3 Capability transfer pricing** — internal pricing on capability calls (extends H2 graph) feeding G13 allocator with realized cross-app value. Proof: pricing engine test.
13. **X3 Enterprise "Loop" SKU** — package Smarter→Tomorrow→Apparently loop as one flat-priced enterprise offering; W6 portfolio war view as the buyer surface. (Mostly packaging + docs + pricing page; depends on C4/D4 bridges live.)
