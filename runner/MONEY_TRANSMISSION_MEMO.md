# COMPLIANCE DECISION: Gaming Operator Wallet/Payout Flow
**Risk Lens: Adversarial Regulator**  
**Audience: General Counsel**  
**Date: 2026-08-02**

---

## VERDICT: HOLD

**Do not expand wallet/payout infrastructure until outside counsel confirms exemption path.**

---

## EXECUTIVE SUMMARY

The operative question: does your gaming operator's wallet accept customer funds and transmit them to external accounts (bank, card, wire)?

- **If YES** → triggered money transmission under 31 CFR § 1010.100(ff); requires federal MSB registration (FinCEN) and state MTL in each operating state
- **If NO** (payout from operator's own funds only) → may escape money transmission entirely
- **If UNCLEAR** → risk-adversary default is registration required

---

## OPERATIVE AUTHORITIES & MATERIAL ASSERTIONS

### 1. **Federal Money Transmission Definition**

**Authority:** 31 CFR § 1010.100(ff) (FinCEN regulation, Bank Secrecy Act)

**Text:** "Money transmitter" means a person that provides money transmission services. A person shall be deemed to be a money transmitter if the person:
1. **Accepts** currency, funds, or value that **substitutes for currency** from one person; AND
2. **Transmits** currency, funds, or value that **substitutes for currency** to another location or person by any means

**Application to gaming wallet:**
- ✓ "Accepts" = customer deposits into platform wallet
- ✓ "Value substitutes for currency" = wallet balance that funds bets and payouts
- ✓ "Transmits" = movement of balance to external bank/card/wire account
- **Conclusion under this definition: wallet flow likely triggers money transmission**

---

### 2. **MSB Registration Requirement (Federal)**

**Authority:** 31 U.S.C. § 5318(h) (Patriot Act); FinCEN guidance, *Application of FinCEN's Regulations to Persons Administering Digital Assets* (Nov 2023)

**Operative Rule:** Any person (including gaming operators) meeting the "money transmitter" definition must:
1. Register with FinCEN via the MSB portal (no fee, renewal every 2 years)
2. File suspicious activity reports (SARs) if cumulative transactions >$5k with indicia of structuring/evasion
3. Implement AML/KYC procedures

**Status if non-compliant:** Civil and criminal penalties; ability to operate payment flow revoked

---

### 3. **State Money Transmitter Licensing**

**Authority:** State-by-state (no uniform federal floor). Example: NY GBL § 518-a; CA Finance Code § 2000 et seq.; TX Finance Code § 59.001

**Operative Rule (risk-adversary reading):**
- Most states define "money transmitter" similarly to federal (accept funds from one person, transmit to another)
- **Gaming-specific carve-out is NOT standard.** (Exception: some states exempt in-state brick-and-mortar casino payouts; online gaming operators in regulated states often still need MTL)
- Multi-state operator must license in each operating state
- State penalties: license revocation, fines, criminal referral

**Example:** New York requires MTL for "any person in the business of selling or issuing payment instruments or stored value." A gaming operator payout flow can easily fall here.

---

## DECISION TREE: WHAT TRIGGERS LICENSING?

| Scenario | Wallet funds come from | Payout goes to | Money Transmission? | Action |
|----------|------------------------|----------------|-------------------|--------|
| Player deposits $100, loses bet | Operator's account | N/A | **NO** (no transmission) | Proceed |
| Player deposits $100, wins $200, requests payout | **Customer's wallet** | Player's bank account | **YES** (federal + state) | Require registration |
| Player deposits $100, platform transfers to payment processor | **Customer's wallet** | Processor custody | **YES** (federal + state) | Require registration |
| Player wins, operator pays from operator's gaming revenue | Operator's own funds | Player's bank account | **PROBABLY NO** (single entity) | Review with counsel |

---

## WHAT WOULD CHANGE THE CONCLUSION?

### Condition 1: Clear Gaming Exemption in Target States
**If and only if:** You operate exclusively in states with explicit regulatory exemptions for licensed gaming operators' payouts
- **Example:** Nevada Gaming Commission, if you have physical license. *(Not true for online-only operators.)*
- **Action:** Obtain written exemption letter from state regulator; document in compliance file

### Condition 2: Third-Party Payment Processor Holds Customer Funds
**If:** Customer deposits flow directly to a licensed third-party processor (e.g., PayPal, Stripe, a licensed payment processor), and your operator never takes custody of customer funds
- **Authority:** FinCEN treats processor as the money transmitter, not the operator
- **Action:** Verify processor's MSB registration; ensure contract assigns AML/compliance obligations

### Condition 3: Domestic Gaming License with Regulator Preemption
**If:** Your state gaming regulator issues a licensed domestic operator and explicitly preempts state MTL requirements *and* FinCEN confirms it in writing
- **Example:** Some states' gaming compacts preempt overlapping federal requirements
- **Action:** Obtain dual confirmation (state + FinCEN); expensive and uncertain

---

## RISK TIERS (Adversarial Lens)

| Tier | Risk | Current State |
|------|------|---------------|
| **Red** | Wallet holds customer funds; payouts go to customer bank accounts; no MSB registration; multi-state | **Most likely; DO NOT PROCEED** |
| **Yellow** | Same, but funds held by licensed third-party processor; you process bets only | **Lower; still requires processor review** |
| **Green** | Licensed brick-and-mortar casino in one state only; payout only via cage/card; explicit state exemption letter | **Unlikely for online operator; requires documentation** |

---

## RECOMMENDED IMMEDIATE ACTIONS

### Before Code/Infrastructure Change:
1. **Retain outside counsel** (fintech/payments law firm with gaming lic.; recommend Big Law with MSB practice)
2. **Document current flow:** Trace every customer dollar (deposit → wallet → withdrawal)
3. **Identify all operating states** (or prospective states)
4. **Obtain state-by-state exemption analysis** (counsel can request advisory letters from regulators)
5. **Parallel FinCEN inquiry:** File an optional advisory to FinCEN, asking if flow constitutes money transmission (slow; expect 60+ days)

### If You Proceed Without Registration:
- **Exposure:** FinCEN/state civil penalties ($100k–$1M+ per jurisdiction); criminal prosecution (rare, but possible); immediate cease-and-desist
- **Mitigation cap:** Even if you register retroactively, FinCEN may treat it as wilful non-compliance during gap period

### If You Register:
- **Cost:** ~$5k–$15k per state + compliance infrastructure (AML officer, SAR filing, audit trail)
- **Timeline:** 30–60 days per state MTL application (some states batch; others are slow)
- **Benefit:** Eliminates existential regulatory risk; allows expansion

---

## FINAL VERDICT MATRIX

| **Verdict** | **If** | **Then** |
|-----------|--------|---------|
| **PROCEED** | Counsel confirms: (a) no customer wallet, OR (b) third-party processor holds all funds, OR (c) explicit state exemption + FinCEN confirmation | Conditional on legal sign-off; require board memo |
| **HOLD** | Operator holds customer wallet funds AND transmits to external accounts AND no exemption letter | **Current state: stop expansion; do not launch new payout methods** |
| **ESCALATE** | Uncertainty remains after counsel review | Refer to Board/CEO; make business call on registration cost |

---

## SUPPORTING CITATION CHECKLIST

- [ ] 31 CFR § 1010.100(ff) — FinCEN money transmitter definition
- [ ] 31 U.S.C. § 5318(h) — Patriot Act MSB registration mandate
- [ ] FinCEN, *Application of FinCEN's Regulations to Digital Assets* (Nov 2023)
- [ ] State MTL statute for each operating jurisdiction (e.g., NY GBL § 518-a)
- [ ] Operator's gaming license (if any) — does it preempt MTL?
- [ ] Payment processor's MSB registration (if applicable)
- [ ] Current payout contract with payment processor (if any)

---

## MEMO CAVEATS

This memo outlines regulatory structure, not legal advice. Outside counsel must:
- Review actual fund flows (not hypothetical)
- Obtain state-specific exemption letters
- Assess criminal exposure under 18 U.S.C. § 1960 (unlicensed money transmission — only triggered if wilful)
- Draft compliance program if registration required

**Outside counsel should be retained before any design changes.**

---

**Prepared for:** [GC name]  
**To be reviewed by:** Outside counsel (fintech/payments) + Board (if registration cost is material)  
**Decision deadline:** [DATE GC will act]
