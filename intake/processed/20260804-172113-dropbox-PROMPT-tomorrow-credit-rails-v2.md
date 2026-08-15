# tomorrow: credit rails v2 — DCC/DSA forgivable-credit rail, IOI-traceable Risk Layers, pre-issuance offset fusion

SUBMITTED-BY: kalepasch@gmail.com (operator decision 2026-08-04)

ACTIVATION NOTE 2026-08-04: hold released by operator decision. The original hold preamble ('rename once prerequisite wave lands / after review-gate') is superseded: the review/release gate now exists (release cards at madeus.cc/waves), and the operator directed activation of all held prompts today. Original attribution preserved below.


ORIGINALLY-SUBMITTED-BY: kale@smrter.us (operator/counsel) via Cowork strategy session 2026-07-28. Strategy reference: PORTFOLIO_STRATEGY_V2 Part 11.1-11.3 (READ FIRST).

WORKFLOW: governed_heavy

## 1. Three-rail credit architecture (11.1)
- Rail 1 (exists from the prior wave): condition-to-draw standby. Do not add forgiveness features to it — ever (characterization).
- Rail 2 (BUILD — the forgivable LOC done right): **DCC/DSA-wrapped credit** — on any REAL extension of credit (Bucket-1 loans, drawn lines, SBLOCs), the lender attaches a debt-cancellation/suspension feature for a fee (the 12 CFR Part 37 banking-product shape; expressly NOT insurance for national banks): revenue-index collapse → payments suspend (DSA); key-person death → balance cancels (DCC); adverse regulatory event → principal tranche forgiven. Lender lays cancellation risk off via the parametric swap behind the wall. Build: DCC/DSA product templates (per trigger family), structuring engine, fee pricing, and the **partner-book activation flow** — a lender activates protection features across its EXISTING portfolio ("attach in weeks, fee income to you, risk laid off to capacity"). Caveat flags in-product: state parity for non-bank lenders (ride bank-partner authority), COD-income tax disclosure to borrowers (tax-swarm hook), objective/parametric triggers only.
- Rail 3: escrow-funded premium tier (structuring only; default off).
- Proof: DCC + DSA fixtures structure end-to-end; forgiveness feature CANNOT be attached to a Rail-1 standby (test-enforced); partner-book activation computes per-loan fee + hedge cost across a fixture portfolio.

## 2. Characterization defense engine (11.2 — substance factors as generated artifacts)
- Rail-1 fee pricing must decompose as commitment-fee-like: committed amount + tenor + borrower credit; trigger-probability cost lives in the lender's hedge leg, never surfaced as the client fee driver. Draws are underwritten, market-rate, repayable. Generate a per-deal **defense artifact**: fee decomposition + underwriting record + repayment terms + trigger-as-condition-to-draw language pointers. Expose to partners as a compliance feature.
- BD/SBLOC variant: Rail 1 + suspension-style features only (no outright cancellation) pending BD counsel; Reg T/non-purpose flags in the doc variant.
- Proof: pricing decomposition emitted per fixture deal; defense artifact renders; an actuarial-style fee (trigger-probability-driven) is rejected by a validation test.

## 3. Risk Layers — naming + no-vehicle invariant (11.3)
- User-facing rename everywhere: "Risk Layers" (senior/mezzanine/first-loss) — remove "pool"/"tranche" from UI + docs surfaces. HARD INVARIANT: no collective vehicle exists anywhere (named bilateral ECP legs only → no CPO trigger); add a grep/CI gate for pooled-vehicle constructs and for Reg D/securities terms.
- Proof: rename sweep complete; CI gate present + passing.

## 4. IOI-traceable Risk Layer pricing (11.3)
- Every Risk Layer quote is assembled from ACTUAL logged agentic IOI expressions + relationship willingness signals + the synthetic-seller floor. Persist the derivation (IOI ids, counterparties count, dates, floor) and attach a traceable basis to every participant's price; render it in the capacity console ("your senior-layer quote derives from N live IOIs + synthetic floor at X bps"). This doubles as the reasonable-basis evidence.
- Proof: fixture layer quote carries a complete derivation chain; removing the IOIs degrades the quote to the labeled synthetic floor.

## 5. Pre-issuance offset fusion (11.3 — issuance and offset are ONE motion)
- Before a lender/BD issues any standby line or DCC/DSA feature: show the offset available NOW — direct IOI match (named, indicative bps) | Risk-Layer placement (layer + bps) | synthetic floor — and quote the **ALL-IN spread** (fee income minus hedge cost) at decision time. Same surface as the capacity/principal consoles from the prior wave; embed beside the OTC IOI mesh + autonomous hedging so it reads as one Tomorrow OS flow, very simple: issue → offset → done.
- Proof: fixture issuance flow displays all three offset paths + all-in spread; accepting binds the hedge intent to the issuance record.

## 6. White-label kit + lender/broker PRIVATE ROOMS (round 9; strategy 12.1a)
- White-label: full theming of the client-facing standby/DCC products under the principal's brand (extend the embed SDK: brand tokens, their paper via CADE per-principal variants, their domain).
- Private deal rooms: a lender-only workspace (repurpose the war-room/hosted-room machinery) pre-populated with THEIR book analysis: portfolio scan results, configurable products, IOI-derived offset quotes + all-in spreads, characterization defense artifacts — with platform bots present in-room as analysts answering questions against the uploaded book. PROACTIVE generation: when warehouse demand matches a lender profile, auto-spin their room pre-populated ("$X of standby demand fits your book") + invitation flow. The room IS the sales motion.
- Proof: white-label render under fixture brand; a room auto-generates from fixture warehouse demand + a fixture book; in-room bot answers portfolio questions.

## 7. Adaptive Perpetual Line (round 9; strategy 12.1b)
- Perpetual committed line whose AVAILABILITY re-strikes on objective parametric events — the borrowing-base analog (availability = f(parametric regulatory/operational state)): license granted → grows; adverse ruling → converts to drawn defense funding / forgives via the Rail-2 DCC feature / steps down per objective covenants. No maturity — mirrors the outcome perpetual (4.2) hedging it: the credit product and its hedge are the SAME instrument seen from two sides (pricing exact, offset instant). Fees decompose commitment-style per the defense engine; forgiveness legs live in Rail 2 only.
- Proof: availability re-strike math both directions; the mirrored outcome-perpetual hedge binds 1:1; forgiveness path routes through the DCC wrapper.

## 8. Loan-doc upload → instant configuration (round 9; strategy 12.1c)
- Upload a loan document → extraction stack parses terms (parties, principal, rate, covenants, collateral, tenor) → configurator proposes matching attachable products (DSA on these payment terms; DCC sized to balance; adaptive availability keyed to sector indexes) priced from the internal IOI/probability system, defense artifact generated alongside. BATCH mode: upload a whole tape → per-loan activation analysis ranked by fee income × offset availability. Feeds the private room (item 6).
- Proof: fixture loan doc round-trips to a priced, papered, hedge-matched product proposal; batch tape produces the ranked activation report.

## Constraints
- All material; counsel flags default-OFF for live money; no securities, no pooled vehicles, no per-match financing fees (participant-agent posture stands); disinterested operator invariant grep stays green.
