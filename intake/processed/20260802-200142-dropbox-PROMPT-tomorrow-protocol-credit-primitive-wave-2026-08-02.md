# tomorrow + apparently + darwin-kernel: Protocol wave — open A2A risk-transfer protocol, RRG as credit primitive, closed-loop remediation financing, underwriting-as-a-service, users-as-capacity, agent conduct registry (operator directive 2026-08-02, APPROVED)

SUBMITTED-BY: kale@smrter.us (operator) via Cowork strategy session 2026-08-02. Operator APPROVED in full — build it.

BINDING POSTURE (restated, unchanged): N4 advisory/stale/non-price-forming pricing. N5/N6 — never a pool/CCP/mutualization; multilateral discovery only; execution = named bilateral legs with all-or-nothing consent. No house/affiliate capital ever fills a leg. Zero-spread RUM revenue only. Ledger separation. Non-custodial rails (instruct, never hold). AGENCY: the user's OWN agents negotiate and execute under the user's own mandate — Tomorrow exercises no discretion and issues no recommendations it then executes. Extends: perpetual-spine-v1, strategy-fixes-2026-08-01, recycling-retention-reputation-2026-08-02, apparently-law-docfabric-2026-08-02. Where overlapping, extend/verify — do NOT duplicate.

## 1. Open A2A risk-transfer protocol + embeddable SDK (highest priority — turns the app into a rail)
- Publish the agent-to-agent risk-transfer protocol as a versioned public spec: message types (exposure declaration, IOI, counter, consent, mandate assertion, settlement instruction, attestation reference), the mandate/band consent model, identity + signature scheme, receipt/attestation format, error and dispute semantics. Version it, changelog it, and treat it as a product with its own docs site. Build ON the existing a2a_messages / agent_identities / agent_mandates rails — formalize, do not re-invent.
- Reference SDK (TS first, then Python) + REST/webhook gateway so an EXTERNAL agent — another AI build platform's agent, a corporate treasury agent, a broker or insurer agent — can: declare an exposure, receive predicted-IOI pricing, negotiate within bands, and reach named bilateral execution with capacity on the network. Sandbox environment with synthetic capacity for integration testing.
- Embeddable "hedge this risk" component (script tag / web component / SDK call) that any external platform can drop in, reusing the signed-embed + domain-allowlist machinery from the Apparently Law doc fabric — ONE embed system, now three content types (legal doc, RRG badge, hedge action).
- Partner-platform onboarding kit: quickstart, revenue/RUM metering per partner, per-partner token allowlists, co-branded flows, partner analytics. Target integrators: AI build platforms, dev tool vendors, compliance vendors, accelerators/incubators, fractional-CFO and outside-GC networks.
- Invariants preserved end-to-end: external-agent execution is still named-bilateral inside pre-consented bands; no order book; no click-to-execute; quotes advisory; no house fill. Protocol conformance tests enforce this for third parties (a non-conforming implementation cannot reach execution).

## 2. RRG as a credit primitive — embed into the financing stack
- Lender/investor API + portfolio feed: authenticated, consent-gated access to Residual Risk Statements and RRG for a portfolio of companies, with change notifications (grade moves, coverage lapses, concentration spikes). Buyers: venture debt lenders, revenue-based financiers, VCs monitoring portfolios, banks with startup books, vendor-diligence teams.
- Covenant kit (drafted via the Apparently Law doc fabric): standard clause library referencing RRG by pinned methodology version — maintenance covenants ("maintain RRG ≥ B and coverage ratio ≥ X"), coverage-as-condition-precedent, and LENDER-AS-NAMED-BENEFICIARY structures where an agreed share of a perpetual's payout is directed to the lender on the covered event (payment instruction routes to the lender's account; still non-custodial, still user↔capacity↔beneficiary — never through a platform account).
- Underwriting evidence pack: one-click, receipt-verified bundle a borrower gives a lender (statement, grade, coverage schedule, retention structure, reputation composite, methodology versions).
- Pricing-impact calculator: model the interest-rate/dilution saving a given coverage program produces at a given lender's grid — this is the sales argument to BOTH sides ("this hedge pays for itself in basis points").
- Ship a public RRG methodology paper + versioned spec so third parties can cite and rely on the grade. Reliance/disclaimer terms and the no-guarantee posture drafted by counsel via the doc fabric.

## 3. Closed-loop remediation financing (monetize risk transfer AND risk reduction)
- When a risk is flagged (Illuminati/CADE/Vigil) the user's agent may, within mandate bands, BOTH bind coverage (risk reflex) AND fund the remediation: Apparently/Apparently Law does the fix, paid from Coverage Credits, the LOC facility, or RUM token budget — user's choice, configured in the mandate.
- Loop mechanics: risk incurred → coverage bound → remediation funded and executed → posture score improves → dynamic retention tightens at the next reset → funding cost drops → freed credits fund the next fix. Instrument every step so the loop is visible in telemetry ("this fix cut your funding cost 18bps/mo — payback 4.2 months").
- Remediation marketplace: where the fix exceeds platform capability, route to the expert network / outside counsel with the same funding rails and receipts.
- Guardrail: remediation funding is a service purchase (RUM/credits), never an event-contingent payment from a platform account — ledger separation invariant applies unchanged.

## 4. Underwriting-as-a-service / model provider (arms-dealer position)
- Package the regulatory/legal loss model as a licensable product for carriers, reinsurers, MGAs, and brokers: factor taxonomy, theme common-shock model, trigger-frequency base rates, calibration history (predicted vs. cleared vs. settled), all versioned with receipts and delivered via API + model cards. Combine with the displacement dataset (public sources only) as the market-context layer.
- MGA-readiness track (flagged, counsel-gated, build the rails not the license): the capability to underwrite on a carrier's paper — submission intake, binding authority workflow, bordereaux reporting, claims/attestation handoff — so a carrier partnership can be stood up without a rebuild. Do NOT enable any insurance-writing path without operator + counsel sign-off.
- Sell-side note in all materials: model licensing is analytics, not advice and not a rating agency service; no guarantee of outcomes; methodology versions pinned per license.

## 5. Users as capacity — organic two-sided market
- Any ECP-qualified participant (including hedger users, corporates, family offices, insurers, and later user-side entities that qualify) can post capacity: capacity onboarding flow, standing mandate configuration by theme/jurisdiction/trigger class, collateral requirements, reputation-tier gating, and participation in capacity auctions on equal terms with funds. Role is an attribute of the participant, not a separate product — same book, same instruments, same neutrality rules.
- Coverage Credits may fund a user's capacity commitments (same-pair netting first, custodian sub-account for cross-pair) — a user who has been paid on a hedge can, if ECP-qualified, write capacity on themes they know.
- Hard gates: ECP verification at inception + covenant monitoring (run-off on loss of status); no non-ECP may write swap capacity under any configuration; capacity writing by a user on their OWN referenced exposure or on outcomes they control is BLOCKED (self-referential exclusion — the 180.1 discipline applies symmetrically); concentration and theme caps apply to user-capacity books identically.
- Auction display shows capacity depth by participant class without identifying participants pre-consent.

## 6. Agent conduct registry (portable primitive on darwin-kernel)
- Extend the reputation fabric to a portable AGENT credential: agent identity, controlling principal, mandate scope/version history, negotiation conduct, settlement performance, dispute record, attestation integrity — receipt-backed, versioned, and portable cross-app via darwin-kernel (same pattern as portable ECP determinations).
- Query API + verifiable presentation format so a counterparty agent (internal or external via §1) can check "is this agent authorized and well-behaved?" before negotiating. Revocation and freshness semantics required.
- Design for generality: schema must not assume Tomorrow-specific instruments — this is intended as infrastructure for agent-mediated commerce broadly. Reserve namespace, publish the schema spec alongside the §1 protocol.

## 7. Self-application (customer zero — credibility asset)
- Compute and publish Tomorrow's/Apparently's OWN Residual Risk Statement and RRG; hedge the portfolio's own regulatory exposure through the platform via ordinary named-bilateral execution with third-party capacity (no self-dealing, no affiliate fill — an affiliate may only be the HEDGER, never the capacity).
- Report it every Monthly Funding Fix alongside the funding curve and calibration scores. Add "customer zero" surface to the marketplace directory.

## PROOFS
- Protocol: conformance suite (a non-conforming external implementation cannot reach execution); sandbox e2e where a third-party agent declares exposure → negotiates → executes named-bilateral inside bands; embed component works on an allowlisted external domain and fails closed elsewhere; per-partner RUM metering accurate.
- Credit primitive: portfolio feed respects consent and revocation; covenant kit clauses render with pinned methodology versions; beneficiary-routed payout instruction reaches the lender without touching a platform account; pricing-impact calculator reproduces a fixture lender grid.
- Remediation loop: funded fix updates posture → retention tightens at next reset only, within bounds → telemetry shows payback; remediation spend never debits the risk ledger.
- UaaS: model API returns versioned model cards + calibration history; MGA path is inert behind flags.
- User capacity: non-ECP capacity blocked; self-referential capacity blocked; run-off on ECP loss; caps enforced.
- Conduct registry: verifiable presentation validates; revocation propagates; schema passes a non-Tomorrow instrument fixture.
- Self-application: own RRG computes from receipts; affiliate cannot appear as capacity in any code path.

OPERATOR (logged, never queued):
- Counsel via Apparently Law doc fabric: protocol participation terms + third-party reliance/disclaimer language; RRG covenant kit and lender-beneficiary structures; model-license terms (analytics not advice, not a rating agency); user-capacity participation terms; MGA/carrier structure if pursued.
- Business development: first two protocol integration partners; first lender to reference RRG in a covenant; first carrier conversation for the model license.
- NFA 2-29 review of protocol/partner-facing and RRG-methodology marketing materials.
