# tomorrow + apparently + pmi: Scale wave — vertical replication, benchmark governance & index licensing, policy-impact instrument, capacity-as-a-service, portfolio monitoring, standards stewardship (operator directive 2026-08-02, APPROVED)

SUBMITTED-BY: kale@smrter.us (operator) via Cowork strategy session 2026-08-02. Operator APPROVED in full — build it.

EXPLICITLY OUT OF SCOPE (operator decision — do NOT build, do NOT scaffold, do NOT flag-gate): any sponsored sidecar / dedicated risk vehicle / fund-of-any-kind that Tomorrow or an affiliate sponsors, advises, manages, or administers for fees. That path touches CPO/adviser territory and is deferred pending counsel. Any task that drifts toward vehicle sponsorship must stop and escalate to the operator card.

BINDING POSTURE (unchanged): N4 advisory/stale/non-price-forming pricing. N5/N6 — never a pool/CCP/mutualization; multilateral discovery only; execution = named bilateral legs with all-or-nothing consent. No house/affiliate capital ever fills a leg. Zero-spread RUM revenue only. Ledger separation. Non-custodial rails. AGENCY: the user's own agents act under the user's own mandate — no platform discretion, no recommendation-then-execution. Extends: perpetual-spine-v1, strategy-fixes-08-01, recycling-retention-reputation-08-02, apparently-law-docfabric-08-02, protocol-credit-primitive-wave-08-02. Extend/verify overlaps — do NOT duplicate.

## 1. Vertical replication engine (highest scale multiplier)
- Generalize the spine into a DOMAIN PACK architecture: a vertical is data + config, never a fork. A domain pack = {corpus sources & watch list, trigger taxonomy, factor/theme model, oracle/determination sources, exposure-quantification model, legal doc pack (via Apparently Law doc fabric), displacement comparables, retention/attachment defaults, disclosure data-pack schema}. The perpetual spine, ledger, auction, credit, retention, RRG, reputation, and protocol layers are shared and MUST NOT be duplicated per vertical.
- Build the pack SDK + authoring pipeline so Apparently swarms can generate a candidate domain pack end-to-end (corpus ingest → taxonomy induction → factor model seed → doc pack draft → displacement scan) with a promotion ladder: draft → validated → priced → live (owner gate at "priced" and "live").
- Seed and validate with the existing regulatory/compliance/legal vertical as pack #0 (refactor current config INTO a pack — proof that the abstraction is real), then generate candidate packs for: healthcare reimbursement/coverage determination, construction permitting & zoning, energy interconnection queue, immigration/visa outcomes, agricultural & food certification, government contracting protest/award, clinical trial & FDA pathway. Do NOT launch these — build packs to "validated" and report readiness.
- Cross-vertical benefits must be automatic: shared theme-factor model with vertical dimensions, cross-vertical diversification scoring in bundle construction (a bundle spanning verticals is genuinely less correlated — price it), and a single capacity market that can bid across packs.
- Proof: pack #0 round-trips through the SDK with zero behavior change; a second pack reaches "validated" from source ingest alone; no vertical-specific code exists in spine/ledger/auction/credit modules (lint rule + test).

## 2. Benchmark governance + index licensing (own the reference, not just the venue)
- Elevate the funding curve and theme indices from a data feature to an ADMINISTERED BENCHMARK: published calculation methodology with versioning, input hierarchy (cleared auction prints first, executed bilateral prints second, predicted IOIs only as labeled interpolation), contributor/eligibility rules, outlier and stale-data handling, expert-judgment policy with logged rationale, restatement policy, cessation/fallback language, conflict-of-interest controls, and an oversight-committee workflow with minutes and receipts. Model on IOSCO Financial Benchmark Principles (transparency, methodology integrity, governance) — implement the controls even though no registration is asserted; do NOT claim regulatory status anywhere.
- Benchmark publication service: daily/monthly fixings per theme index and per retention tier, immutable historical archive with restatement audit trail, machine-readable API + signed values, and a public methodology + factsheet site.
- Index licensing rails: license agreement templates (via doc fabric) with methodology-version pinning, permitted-use tiers (reference in a contract, publish, build a listed product, redistribute), usage metering, and an index-provider portal. Target licensees: exchanges (listed dated products referencing a theme index), lenders/insurers referencing in contracts, data redistributors, research.
- Fallback/cessation language must exist BEFORE any third party references a benchmark — no external reference permitted until the cessation policy ships.
- Proof: fixing reproducible from archived inputs; restatement leaves an audit trail; a licensed consumer receives only the pinned version; predicted-IOI inputs can never dominate a fixing where prints exist.

## 3. Policy-impact instrument (PMI flagship — the price of regulation)
- Rule-to-market pipeline: watch Federal Register / agency dockets / state registers (reuse the corpus watch rails); on publication of a proposed or final rule, automatically identify affected themes and cohorts, snapshot pre/post funding rates and predicted IOIs, and compute a Regulatory Cost Signal (basis-point and dollar-equivalent impact on hedging cost for the affected cohort, with confidence bands and methodology link).
- Outputs: (a) live public rule-impact pages with the signal and its derivation; (b) comment-letter evidence packs (market-priced cost evidence formatted for docket submission); (c) a subscription impact feed; (d) retrospective accuracy tracking (predicted vs. realized cost) published openly — accuracy IS the credibility product.
- Distribution: PMI as publisher/steward; Apparently editorial engine ships an item every Monthly Funding Fix; alerting for subscribers on high-impact rules.
- Guardrails: strictly non-partisan, methodology-first framing; no lobbying, no advocacy positions, no predictions of political outcomes; the product is measurement, and it must present cost signals for all affected parties symmetrically. Disclose that signals derive from a market Tomorrow operates.
- Proof: a fixture rule flows publication → cohort identification → signal → published page + evidence pack; retrospective tracker recomputes accuracy from archived fixings.

## 4. Capacity-as-a-service — widen beyond hedge funds (removes the concentration fragility)
- Self-serve capacity onboarding for every eligible participant class: hedge funds, family offices, corporate balance sheets (hedging their own sector while earning uncorrelated carry), insurers/reinsurers, pensions and endowments, sovereign/development funds, and ECP-qualified platform users. Class is an attribute — same book, same instruments, same neutrality, same auction terms.
- Onboarding as configuration, not sales: guided mandate builder (themes, jurisdictions, trigger classes, notional and tenor bands, retention floors, reputation-tier gates, concentration caps), collateral/settlement setup on the non-custodial rails, ECP verification + covenant monitoring with automatic run-off on loss of status, and a capacity readiness score. Reachable through the §1 protocol so an external capital provider's own agent can onboard and bid programmatically.
- Capacity concentration telemetry: platform-level dashboard of capacity depth by class/theme with a target-diversification metric and alerts when any single provider exceeds a configurable share of filled notional — concentration is a tracked platform risk, not an afterthought.
- Hard gates unchanged: no non-ECP writes swap capacity under any configuration; no self-referential capacity (writing on outcomes you control or on your own referenced exposure); per-name and per-theme caps apply identically to every class.
- Proof: a family-office fixture onboards and fills an auction lot end-to-end with zero human sales touch; concentration alert fires on a synthetic over-weight provider; non-ECP and self-referential attempts blocked.

## 5. Portfolio monitoring for capital allocators (fastest distribution channel)
- Portfolio product on the RRG/lender feed: allocators (VCs, venture debt lenders, accelerators, insurers, corporate development, family offices) hold a roster of companies and receive consent-gated Residual Risk Statements, RRG, coverage status, retention adequacy, and concentration analytics ACROSS the portfolio — plus alerts on grade moves, coverage lapse, theme concentration building across holdings (their real hidden risk: twenty portfolio companies exposed to one rule), and newly quantified exposures.
- Roster management: invite/consent flow per company (company-controlled, revocable, scoped — the company sees exactly what the allocator sees), bulk onboarding for a portfolio, and an allocator-branded portfolio report generated each Funding Fix.
- Built-in distribution loop: an allocator inviting a portfolio company to share is a warm onboarding for that company (coverage offer attached); every invited company that hedges deepens the allocator's data. Instrument the loop (invites → activations → coverage attach) as a first-class growth metric.
- Consent supremacy: no company data reaches an allocator without that company's explicit, revocable, version-hashed consent — the invite is a request, never an entitlement, and revocation is immediate.
- Proof: portfolio fixture shows cross-holding theme concentration; consent revocation removes data within one cycle; invite→activation funnel metered.

## 6. Standards stewardship (make the standards durable and citable)
- Treat the four standards — A2A risk-transfer protocol, RRG methodology, benchmark methodology, agent conduct registry schema — as a single governed program: versioned public specs, changelogs, deprecation policy, conformance suites, reference implementations, public docs site, and a stable namespace/identifier scheme reserved across apps (darwin-kernel).
- Adoption instrumentation: track external implementers, licensed benchmark consumers, contracts referencing RRG, and conduct-registry queries as headline platform metrics — standards adoption is the moat's actual scoreboard.
- Citation posture: publish methodology papers with DOIs where practical so third parties (lenders, insurers, researchers, agencies) can cite and rely on them; reliance/disclaimer terms drafted via the doc fabric. No regulatory status claimed for any standard.

## PROOFS (in addition to per-section proofs)
- No vertical-specific code in shared layers; second domain pack validated from ingest alone.
- Benchmark fixing reproducible and restatement-audited; no external reference before cessation policy ships.
- Policy signal pipeline runs end-to-end on a fixture rule with published retrospective accuracy.
- Capacity onboarding completes with no human touch; concentration alerting live; ECP/self-referential gates enforced.
- Allocator portfolio consent, revocation, and funnel metrics all pass.
- Every standard has a version, changelog, conformance suite, and reference implementation before external promotion.

OPERATOR (logged, never queued):
- Counsel via Apparently Law doc fabric: benchmark administration posture and cessation/fallback language; index license terms; RRG reliance/disclaimer for third-party contract use; policy-impact publication posture (non-advocacy, disclosure that Tomorrow operates the underlying market); allocator data-sharing and consent terms; capacity participation terms per participant class.
- Business development: first exchange conversation for a listed product referencing a theme index; first allocator portfolio pilot; first non-fund capacity provider (family office or corporate).
- NFA 2-29 review of benchmark, policy-signal, and allocator-facing materials.
- REMINDER: sponsored sidecar / vehicle remains OUT OF SCOPE pending counsel — do not authorize any task that drifts toward it.
