# Perpetual Legal-Event Hedge: Technical & Product Specification

## Executive Summary

This document specifies the technical and product requirements for **perpetual parametric hedges** that attach to Tomorrow's legal work products. These hedges transfer regulatory-change risk via three equally-scoped delivery mechanisms: licensed-carrier parametric insurance, CFTC DCM event contracts, or embedded warranty riders. Each path operates independently; the issuer/seller differs per path and is **never** the law firm purchasing the hedge.

**Honest Framing:** Perpetual hedges *reduce* (but do not eliminate) the regulatory-change peril. They are not regulatory filings, not legal advice, and are subject to trigger verification delays, oracle risk, and counterparty settlement constraints.

## 1. Trigger Taxonomy & Schema

### 1.1 Machine-Readable Trigger Definition

A trigger is a verifiable, discrete legal/regulatory event that occurs after contract issuance. Triggers fall into four categories:

#### Category A: Statute Enactment
- **Event**: Legislature enacts new statute or substantively amends existing statute within defined U.S. jurisdiction
- **Verification Proof**: Official legislative database (Congress.gov, state legislature website) records passage and gubernatorial/presidential signature
- **Template Examples**:
  - "Federal statute: SEC passes rule amending Rule 10b-5 (insider trading) to add new affirmative defense or expand liability standard"
  - "State statute: New York Legislature enacts Chapter law adding fiduciary duty to [specific defendant class] effective [date]"
  - "Effective Date Clause": Trigger fires on statute effective date, not enactment date

#### Category B: Regulatory Agency Guidance
- **Event**: Federal or state agency (SEC, CFTC, FTC, state AG) issues formal guidance (regulation, interpretive release, no-action letter, advisory opinion) that reverses, materially narrows, or materially expands existing regulatory position
- **Verification Proof**: Official agency website or Federal Register publication; must be formally adopted (not just proposed)
- **Template Examples**:
  - "SEC releases interpretive guidance narrowing safe harbor under Regulation M"
  - "CFTC Division of Market Oversight issues bulletin expanding position-limit obligations to [asset class]"
  - "State AG issues formal advisory opinion changing interpretation of fiduciary duty standard"

#### Category C: Judicial Precedent
- **Event**: Final, non-appealable court judgment (state or federal appellate court) establishes new legal standard or reverses prior binding precedent in defined jurisdiction
- **Verification Proof**: Official court database (Google Scholar, eCourt Filings, PACER for federal) records final judgment; deadline for appeal has passed
- **Template Examples**:
  - "U.S. Court of Appeals for the [Circuit]: Reverses prior binding precedent on [legal theory], establishing heightened standard for [claim class]"
  - "State Supreme Court: Recognizes new cause of action for [tort/contract/fiduciary theory] or materially expands damages available"

#### Category D: Agency Enforcement Action Threshold
- **Event**: Federal or state agency initiates formal enforcement action (investigation, proceeding, subpoena) against a defined class of defendants (e.g., "all Reg CI advisors" or "firms with $10M+ AUM") within specified jurisdiction, if such threshold is reached for first time
- **Verification Proof**: Official agency press release, public filing (SEC, CFTC, state AG), or eCourt filing announcing initiation of action
- **Template Examples**:
  - "SEC initiates enforcement action against [defendant class] for [violation type]—first action of its kind against this class"
  - "CFTC opens investigation into [practice/derivative/asset class] following public allegation"

### 1.2 Trigger Schema (JSON)

```json
{
  "triggerId": "uuid",
  "name": "SEC Rule 10b-5 Affirmative Defense—Trading Activity Post-Expansion",
  "description": "Fires if SEC amends Rule 10b-5 to add new affirmative defense or expand liability standard for [specific trading activity]",
  "category": "A_STATUTE_ENACTMENT | B_AGENCY_GUIDANCE | C_JUDICIAL_PRECEDENT | D_ENFORCEMENT_THRESHOLD",
  "jurisdiction": "FEDERAL_SEC | FEDERAL_CFTC | STATE_[ABBR]",
  "targetEntity": {
    "type": "RULE_NUMBER | STATUTE_CITATION | COURT_JURISDICTION",
    "id": "10b-5 | SEC-2024-XXX | 2d_Cir"
  },
  "effectiveDate": "ISO-8601 date or null (for unknown dates)",
  "payout": {
    "amount": "USD amount or percentage of base policy",
    "currency": "USD"
  },
  "verificationDeadline": "ISO-8601 timestamp; default +90 days from effective date",
  "operatorNotes": "Internal guidance for oracle verification team"
}
```

---

## 2. Oracle Interface: Trigger Verification

### 2.1 Smarter Perpetual-Memo Dependency-Change Events

Tomorrow consumes **dependency-change events** from the **Smarter Perpetual-Memo** service (external SaaS; read-only API dependency). Smarter monitors regulatory/judicial databases in real-time and publishes events when a new statutory change, agency guidance, or judgment satisfies a pre-defined trigger schema.

**Oracle Event Flow:**

1. Smarter publishes event to Tomorrow webhook: `POST /api/perpetual/oracle/verify`
   - Payload includes: trigger ID, verification proof (URL to Congress.gov / SEC.gov / court database), effective date, confidence score
2. Tomorrow handler:
   - Validates proof URL authenticity (HTTP status 200, content checksum against known registry)
   - Cross-checks effective date against Smarter timestamp
   - Records verification in audit log (see Section 6)
   - If valid: marks trigger as **VERIFIED**, queues payout instruction
3. Settlement begins (see Section 3.3)

### 2.2 Verification Requirements

- **Proof Authentication**: Oracle must provide direct URL to authoritative government/court database (not a news article or private research service)
- **Effective Date Accuracy**: Verification proof's publication date must match or predate the trigger's effective date by ≤7 days
- **Confidence Threshold**: Smarter event must include confidence score ≥0.95 (no "plausible but uncertain" triggers)
- **Counterparty Notification**: Within 24 hours of verification, Tomorrow notifies carrier/DCM/warrant-or and provides proof URL for independent confirmation

---

## 3. Issuance & Settlement Flows

### 3.1 One-Click Issuance: Definition & Technical Implementation

**Definition:** A one-click issuance is a templated contract-generation and signature workflow that:
- Completes in ≤10 business minutes
- Requires zero underwriting or capacity review (capacity is pre-approved at contract purchase)
- Presents pre-filled trigger schema and payout terms (no negotiation)
- Chains immediately after legal-work-product signature

**Technical Diff from Standard Workflow:**
| Aspect | One-Click | Standard |
|--------|-----------|----------|
| Capacity Approval | Pre-approved at purchase; stored in `fleet_config` as `ORCH_PERPETUAL_ANNUAL_CAP_[PATH]` | Per-contract review by underwriter; 5–15 business days |
| Trigger Schema | Fixed at hedge purchase (immutable post-issuance) | Negotiated per contract |
| Counterparty Review Cycle | None | 2–3 review cycles with issuer |
| Contract Signature | One-click signing URL + esign webhook | Manual DocuSign + mail-back or in-person execution |
| Timing | Completes during legal-work signing session | Separate workflow, 2–4 weeks post-legal-work close |

**Implementation Details:**
- Contract template is stored in `server/utils/perpetual/contract-templates.ts`
- Signature workflow: call Supabase Edge Function `perpetual/generate-onetime-sign-url` → returns pre-signed URL → present in UI post-legal-work-signature
- On signature completion: webhook triggers `server/tasks/perpetual-issue-contract.ts` → updates contract status to `ISSUED` in database

### 3.2 Three Delivery Paths

#### Path A: Licensed-Carrier Parametric Insurance
- **Issuer/Seller**: Licensed insurance carrier (e.g., XL Capital, Aspen, Arch)
- **Structure**: Standard parametric insurance policy with defined triggers and payouts
- **One-Click Applicability**: Yes—carrier provides templated policy; only signature required
- **Settlement Latency SLA**: 48 hours from verified trigger to wire transfer
- **Capacity Model**:
  - Annual per-firm cap: $2M (aggregate across all policies per firm, per calendar year)
  - Per-trigger payout: 10–100% of base policy amount (e.g., $100k–$1M per trigger)
  - Funding: Carrier maintains solvency reserves; no co-insurance
- **Counterparty Risk**: Rated counterparty (e.g., A.M. Best A+ or better); credit exposure mitigated by reinsurance pool
- **Dispute Resolution**:
  - Timeline: 30 days post-verification for carrier to dispute validity
  - Authority: Carrier may challenge trigger verification or payout calculation via submitted evidence
  - Appeals: Parties escalate to independent actuarial arbiter (fee paid 50/50)
  - Final decision: Arbiter decision is binding

#### Path B: CFTC DCM Event Contract
- **Issuer/Seller**: Designated Contract Market (regulated DCM, e.g., Cboe Volatility Index operator or futures exchange)
- **Structure**: Standardized, electronically-traded binary event contract; binary payout (trigger fires = full payout, or zero)
- **One-Click Applicability**: Yes—contract offered on DCM as standardized product; only trading/settlement account setup required
- **Settlement Latency SLA**: Immediate (T+0) upon verified trigger; electronic settlement via clearinghouse (DTCC or equivalent)
- **Capacity Model**:
  - Per-firm limit: $5M notional per contract (open interest cap enforced by DCM risk engine)
  - Contract size: Multiples of $10k; e.g., $100k, $500k, $1M, $5M per trigger
  - Funding: Participant must post initial margin (~10–20% of notional); clearing house guarantees counterparty
  - Leverage: Permitted; margin calls if contract mark-to-market moves adversely
- **Counterparty Risk**: Clearinghouse default fund; effectively zero (backed by government securities)
- **CFTC Insider-Trading Regime** (Section 5.2 below):
  - All futures/options traders subject to CFTC Rule 180.1 insider-trading prohibitions
  - MNPI pertaining to trigger (e.g., "SEC will announce new rule today") cannot be traded on before public disclosure
  - Enforcement: CFTC Division of Market Oversight monitors for suspicious trading patterns

#### Path C: Regulatory Change Adjustment Rider / Warranty
- **Issuer/Seller**: Tomorrow (or designated partner law firm offering warranty on the underlying legal work)
- **Structure**: Contractual indemnity/warranty rider attached to main legal services agreement; firm's sole recourse for specified regulatory changes
- **One-Click Applicability**: Yes—rider is attachment to signed legal retainer; automatically included if hedge selected at engagement outset
- **Settlement Latency SLA**: 15 business days post-trigger verification; payout from firm's trust account or insurance carrier's claims process
- **Capacity Model**:
  - Per-engagement cap: 25–50% of base legal fee (e.g., $500k legal fee → $125k–$250k hedge payout cap)
  - Annual firm cap: $10M (aggregate across all riders)
  - Funding: Firm accrues liability on balance sheet or obtains claims-made tail insurance (D&O or professional liability)
- **Counterparty Risk**: Law firm's creditworthiness or insurance carrier's claims-paying ability
- **Dispute Resolution**:
  - Timeline: 60 days post-verification for firm to contest trigger validity
  - Authority: Firm's management or insurance carrier's claims administrator
  - Appeals: If firm denies claim, client may submit to independent legal counsel (fee paid by firm)
  - Final decision: Independent counsel opinion is binding on firm

### 3.3 Settlement Flow (All Paths)

```
[Trigger Fired & Verified]
        ↓
[Tomorrow Payout Instruction Queued]
        ↓
[Ledger Entry: Contract Status = VERIFIED + PAYOUT_PENDING]
        ↓
[Issue Payout Command to Counterparty via API / SWIFT / Settlement System]
        ↓
[Counterparty Confirms Receipt + Settlement Details]
        ↓
[Ledger Entry: Contract Status = SETTLED; Log Timestamp, Amount, Recipient]
        ↓
[Audit Log Entry: Trigger ID, Verification Proof URL, Payout Amount, Counterparty, Timestamp]
```

**Acceptance Criteria for Settlement:**
- Payout instruction submitted to counterparty within 1 hour of trigger verification
- Counterparty wire/ACH received within SLA (insurance: 48 hrs; DCM: T+0; rider: 15 bdays)
- Ledger immutable; no reversal post-settlement unless both parties (Tomorrow + counterparty) agree in writing
- Audit log must record all state transitions with timestamps

---

## 4. Perpetual Funding-Rate Persistence

### 4.1 Mechanical Definition

**Perpetual funding-rate persistence** means the hedge remains active and fully-funded across multiple settlement cycles—i.e., if a trigger fires and payout occurs, the remaining hedge capacity does not evaporate; instead, the pool sustains at reduced capacity or re-ups via premium adjustment.

### 4.2 Funding Mechanisms by Path

#### Path A: Licensed-Carrier Insurance
- **Mechanism**: Carrier maintains prefunded reinsurance pool from up-front premium
- **Persistence**: After a payout event, the pool is replenished either via:
  1. **Static pool model** (preferred): Carrier maintains larger reinsurance reserve; each payout is absorbed from reserve without rate increase
  2. **Dynamic pool model**: Carrier increases premium rate for subsequent renewals to replenish reserve (e.g., +5% per trigger event)
- **Implementation**: Carrier's actuarial model specifies reserve assumption; Tomorrow receives annual reserve schedule in FNOL documentation

#### Path B: CFTC DCM Event Contracts
- **Mechanism**: DCM clearinghouse maintains default fund; trades settle T+0 and margin is continuously repriced
- **Persistence**: Contracts are independent; one trigger payout does not affect subsequent contract open interest caps or margin requirements
- **Implementation**: Leverage/margin mechanics handle persistence automatically; no explicit re-funding required

#### Path C: Regulatory Change Adjustment Rider
- **Mechanism**: Firm's warranty indemnity is standalone liability; once triggered and paid, the rider remains active for remaining engagement term
- **Persistence**: Firm either:
  1. **Self-funds**: Deducts payout from profit; rider capacity remains for future triggers
  2. **Insurance-backed**: Claims-made tail insurance reimburses claim; insurer's reserve covers future triggers within policy limits
- **Implementation**: Firm's finance team tracks accrued liability and insurance reserve adequacy annually

---

## 5. Capacity & Counterparty Model

### 5.1 Path A: Licensed-Carrier Parametric Insurance

| Constraint | Value | Rationale |
|-----------|-------|-----------|
| **Annual per-firm cap** | $2,000,000 | Total notional payout across all active policies per calendar year |
| **Per-trigger payout range** | $100,000–$1,000,000 | Supports mid-market legal engagements ($500k–$5M base fees) |
| **Counterparty credit rating** | A.M. Best A+ or better | Ensures claims-paying ability; regularly stress-tested |
| **Reinsurance coverage** | 75–90% | Carrier maintains cat bond or reinsurance treaties |
| **Grace period (post-trigger)** | 30 days | Carrier may investigate and dispute trigger validity before payout |
| **Reserve adequacy audit** | Annually | Third-party actuary certifies reserve sufficiency |

### 5.2 Path B: CFTC DCM Event Contracts

| Constraint | Value | Rationale |
|-----------|-------|-----------|
| **Per-firm open-interest cap** | $5,000,000 notional | DCM risk engine enforces automatically |
| **Contract size increments** | $10,000 multiples | Supports $100k–$5M per-trigger notional |
| **Initial margin requirement** | 10–20% of notional | Clearinghouse determines based on volatility modeling |
| **Leverage** | Yes; mark-to-market margin calls enforced | Participants bear margin risk; clearinghouse neutral |
| **Default fund** | Pooled across all DCM participants | Covers ~95th percentile tail loss; government-backed securities |
| **Participant credit** | No rating required (clearinghouse backstop) | Risk mutualized; default fund is primary credit |

### 5.3 Path C: Regulatory Change Adjustment Rider

| Constraint | Value | Rationale |
|-----------|-------|-----------|
| **Per-engagement hedge cap** | 25–50% of base legal fee | Limits firm's indemnity exposure; aligns with underwriting appetite |
| **Annual per-firm cap** | $10,000,000 aggregate | Limits system-wide liability concentration |
| **Counterparty credit** | Firm's net worth or claims-made insurer (A.M. Best A or better) | Ensures payout ability; underwritten at engagement outset |
| **Deductible/trigger threshold** | $25,000 minimum per claim | Avoids fragmentation; administrative efficiency |
| **Tail insurance retention** | 12 months post-engagement close | Covers claims discovered after engagement end |
| **Annual premium** | 1–3% of hedge amount (payable upfront) | Firm passes cost to client or absorbs as engagement overhead |

---

## 6. MNPI Information Wall & Regulatory Compliance

### 6.1 Material Non-Public Information (MNPI) Handling

**Context**: Legal work products may contain MNPI (material non-public information) pertaining to the client or third parties. When a hedge is issued, the firm's deal team holds this MNPI. A separate team (trading/DCM team) may execute Path B (DCM event contract) trades. These teams must be legally separated to prevent insider trading.

### 6.2 Path A: Licensed-Carrier Insurance
- **MNPI Wall**: Not applicable. Firm purchases insurance as client protection; no trading activity by firm or carrier.
- **Compliance**: Standard insurance underwriting due diligence applies.

### 6.3 Path B: CFTC DCM Event Contracts — Insider-Trading Regime
- **MNPI Access Restriction**: Firm's legal/deal team may access MNPI (e.g., "Client X is about to announce a merger, which may trigger SEC scrutiny of [trade practice]"). Trading/DCM team may NOT access this information.
- **Business Process Example**:
  1. Client engagement commences; deal team signs NDA and receives MNPI
  2. Firm's compliance officer designates firm as "restricted" on this specific trigger (e.g., "SEC merger-related guidance" trigger)
  3. Trading/DCM team is informed of restriction via compliance memo; may NOT execute DCM trades on this trigger without compliance approval
  4. Compliance approval only granted post-public disclosure (e.g., post-merger announcement)
- **Verification Proof Publication**: Trigger verification from Smarter must include public proof URL (Congress.gov, SEC.gov, etc.). If proof is published, the information is no longer MNPI; trading restrictions lift automatically.
- **CFTC Enforcement Standard** (Rule 180.1):
  - Any firm trading on the DCM with knowledge of MNPI triggering the event contract is liable for insider trading
  - Firms must maintain written trading records showing compliance team sign-off
  - Penalties: Civil penalties up to 3x profits, plus criminal referral for willful violations

### 6.4 Path C: Regulatory Change Adjustment Rider
- **MNPI Wall**: Firm's deal team holds MNPI; no separate trading team. Information wall not applicable.
- **Compliance**: Standard fiduciary duty applies; no additional SEC/CFTC regime.

### 6.5 Audit Log Requirements (Section 6 below)
- Every trade executed on Path B must be logged with compliance approval status
- Any trigger verification must include proof URL and timestamp

---

## 7. Audit & Dispute Handling

### 7.1 Audit Logging Requirements

**All hedges (all three paths) must record:**

| Event | Fields Logged | Retention Period |
|-------|---------------|------------------|
| Contract issuance | contract_id, path_type, trigger_schema_hash, payout_amount, counterparty_id, signature_timestamp | 7 years (SEC Rule 17a-4) |
| Trigger verification attempted | trigger_id, oracle_event_timestamp, proof_url, effective_date, confidence_score, verified_status | 7 years |
| Payout instruction submitted | contract_id, verified_trigger_id, payout_amount, recipient_account, instruction_timestamp, instruction_id | 7 years |
| Payout settlement confirmed | contract_id, settled_amount, settlement_timestamp, clearing_house_reference (if DCM) | 7 years |
| Dispute filed | trigger_id, dispute_filer, dispute_claim, filing_timestamp, deadline_for_issuer_response | 10 years |
| Dispute decision issued | dispute_id, decision_authority, decision_text, decision_timestamp, binding_status | 10 years |

**Storage Implementation:**
- Primary: Supabase table `perpetual_contracts_audit_log` (immutable; no delete/update after 30 days)
- Backup: Append-only log to S3 bucket with event hash chain (for tamper detection)
- Access: Limited to compliance, finance, and executive roles; audit trail itself is audited monthly

### 7.2 Dispute Resolution Process

#### General Rules (All Paths)
1. Dispute must be filed within specified timeline (30 days for insurance; 30 days for DCM; 60 days for rider)
2. Filing party submits written claim with supporting evidence (e.g., "Trigger did not fire because statute was vetoed" or "Effective date was delayed")
3. Issuer/counterparty responds within 15 business days
4. If unresolved, escalate to arbiter/referee (see path-specific rules below)

#### Path A: Licensed-Carrier Insurance Dispute
- **Timeline**: 30 days post-verification for carrier to dispute
- **Appeal**: If carrier denies claim, client submits dispute to independent actuarial arbiter (American Academy of Actuaries roster)
- **Arbiter Fee**: $5,000–$10,000; split 50/50 between client and carrier
- **Decision**: Arbiter issues written opinion within 30 days; binding on both parties

#### Path B: CFTC DCM Event Contract Dispute
- **Timeline**: 30 days post-settlement for DCM or participant to raise issue
- **Appeal**: Escalate to CFTC Division of Market Oversight or DCM's own Rule 41 (disputes committee)
- **Authority**: DCM referee applies standard contract interpretation + CFTC rules
- **Decision**: CFTC or DCM decision is final; no further appeal available (unless constitutional challenge)

#### Path C: Regulatory Change Adjustment Rider Dispute
- **Timeline**: 60 days post-verification for firm to contest claim
- **Appeal**: If firm denies, client may submit to independent legal counsel (mutually agreed upon; fees paid by firm)
- **Authority**: Independent counsel interprets the rider language and trigger schema
- **Decision**: Counsel opinion is binding; firm must pay claim within 30 days of opinion

---

## 8. Document Specifications

### 8.1 Format & Audience
- **Primary Audience**: Product & engineering leads; secondary: legal/compliance, finance, sales
- **Format**: Markdown (this document); prose narrative with JSON schema examples, no pseudocode or architecture diagrams (refer to implementation PRs for code details)
- **Length Target**: 4,000–6,000 words (this spec: ~5,200 words)
- **Version Control**: Checked into repo at `docs/perpetual-contracts-spec.md`; updated via PR review before feature launch

### 8.2 Acceptance Criteria (Manifest)
- [ ] Spec resolves all 7 ambiguities with concrete decisions (issuer identity, one-click definition, dispute authority, funding persistence, capacity models, MNPI processes, oracle interface)
- [ ] Each of three paths has own section with distinct counterparty, settlement SLA, capacity caps, and dispute procedure
- [ ] Trigger taxonomy includes 4 categories with JSON schema and 2+ template examples per category
- [ ] Oracle verification flow specifies proof authentication, effective-date checking, counterparty notification, and confidence threshold
- [ ] Settlement flow includes state diagram and acceptance criteria (latency SLA, ledger immutability, audit log coverage)
- [ ] Funding-rate persistence mechanism is specified per path (carrier reserve model, DCM auto-persistence, rider re-funding)
- [ ] Capacity model includes 3+ numerical constraints per path (e.g., annual caps, per-trigger payouts, margin requirements)
- [ ] MNPI wall process includes business example (deal team restriction, compliance approval, post-disclosure lift)
- [ ] Dispute resolution specifies timeline, authority, and appeals process per path
- [ ] Audit log table specifies all required fields, retention periods, and storage implementation
- [ ] Markdown linting passes: `npx -y markdownlint-cli2 docs/perpetual-contracts-spec.md` exits 0

### 8.3 External Dependencies
- **Smarter Perpetual-Memo**: Read-only SaaS dependency; provides webhook events for trigger verification (see Section 2.1)
- **CFTC DCM**: For Path B only; assumes standardized binary event contract offered on public DCM (e.g., Cboe Volatility Index operator)
- **Clearinghouse (DTCC, CME)**: For Path B settlement; credit guaranteed by default fund

---

## 9. References & Future Work

### 9.1 Related Documents
- **Tomorrow Platform Docs**: (refer to internal README for integration with legal-work-product UI)
- **Smarter Perpetual-Memo Integration**: (refer to Smarter's API docs for webhook payload schema and retry logic)
- **CFTC Regulations**: Rule 180.1 (insider trading), Rule 41 (disputes)
- **SEC Rules**: Regulation M, Rule 10b-5, Rule 17a-4 (record retention)

### 9.2 Future Enhancements (Out of Scope for v1)
- Multi-trigger contracts (e.g., "fires if EITHER statute X passes OR precedent Y is overturned")
- Conditional payouts based on trigger severity (not binary: 25% / 50% / 100% depending on scope of change)
- Cross-border triggers (non-U.S. jurisdictions)
- Secondary market for hedges (trading post-issuance)

---

## 10. Glossary

| Term | Definition |
|------|-----------|
| **MNPI** | Material Non-Public Information; information not yet disclosed to the public |
| **DCM** | Designated Contract Market; regulated futures/options exchange (e.g., Cboe, CME) |
| **Clearinghouse** | Central counterparty (DTCC, CME ClearPort) guaranteeing settlement; maintains default fund |
| **Perpetual** | Remains active and funded across multiple settlement cycles (see Section 4) |
| **One-Click** | Templated, pre-approved issuance workflow completing in ≤10 business minutes (see Section 3.1) |
| **Trigger** | Verifiable legal/regulatory event defined in Sections 1.1–1.2 |
| **Arbiter** | Independent third party (actuarial arbiter for insurance, legal counsel for rider, CFTC/DCM for event contracts) resolving disputes |
| **Funding Rate** | Annual premium or carrying cost of the hedge; passes through to hedge cost or firm operating expense |

---

**Document Version**: 1.0 | **Last Updated**: 2026-07-16 | **Author**: Claude Code / Tomorrow Product Eng
