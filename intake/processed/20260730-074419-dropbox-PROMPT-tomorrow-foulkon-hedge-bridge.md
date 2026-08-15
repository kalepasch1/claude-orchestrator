# Tomorrow ↔ Foulkon — Hedge Bridge (TransferSpec population + 1-click activation)

Operator directive 2026-07-30. Foulkon gradient options must carry Tomorrow swap-risk data where
relevant: probability, cost, value — and 1-click hedge activation. The schema is already shipped
(`TransferSpec` in illuminati `server/utils/rapidGradient.ts`); this build populates it.

## What to build
1. **S2S quote endpoint on Tomorrow** (reuse the existing HMAC S2S pattern — gaming/PLOEH bridges):
   `POST /api/s2s/foulkon/hedge-quote` — input: risk descriptor (vertical, jurisdiction, trigger
   class e.g. 'enforcement action within 24mo' / 'license application denied' / 'rule change
   adverse'), notional band, company eligibility class. Output: instrument (from the permitted
   swap-only allowlist — binary event swaps on regulatory outcomes are the natural fit),
   indicative premium BAND (from indicativeReference — STALE, ADVISORY, non-price-forming N4
   posture preserved), what pays out and when, expected-value note (premium vs. expected covered
   loss, stated honestly including when the hedge is NOT worth it).
2. **Foulkon-side enrichment**: after the tribunal returns, a fail-soft enricher calls the quote
   endpoint for options whose risk class maps to a hedgeable trigger (cache quotes 15min; never
   block the gradient — transfer data arrives as a follow-up patch to the rendered card if slow).
3. **Eligibility gate, structural**: ECP → direct bilateral IOI flow; non-ECP → route to the
   **Adaptive Perpetual Line** pathway (the non-ECP product surface); ineligible → show the
   number anyway ("transfer would price at ~X — unavailable at your eligibility tier") because
   the PRICE of the risk is informative even when the instrument isn't accessible.
4. **1-click activation**: click → Tomorrow IOI flow (bilateral, no click-to-execute posture
   preserved — the click submits the INDICATION and opens the standard consent flow, it never
   executes a trade). Cost/timing/what-happens-next displayed before the click.
5. **Value honesty rule**: every quote carries the expected-value note; where premium > expected
   covered loss, SAY SO ("this hedge prices above the modeled risk — remediation is cheaper").
   The tool's credibility rests on recommending against itself when the math says so.

## Compliance posture (unchanged, binding)
Swap-only allowlist; §2(h)(7) bilateral IOI, no order book, no click-to-execute; ECP gating
enforced server-side on Tomorrow; indicative pricing is stale/advisory/non-price-forming (N4);
Foulkon displays, Tomorrow prices — Foulkon never forms a price.
