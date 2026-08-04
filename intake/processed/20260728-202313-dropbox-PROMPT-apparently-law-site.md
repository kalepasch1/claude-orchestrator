# apparently-law: new site (Nuxt/Supabase/Vercel/Tailwind), first-option routing, boutique network, token/subscription pricing

SUBMITTED-BY: kale@smrter.us (operator/counsel) via Cowork strategy session 2026-07-27. Rule 5.4/ABS structure APPROVED by operator. (Rename to PROMPT-… to activate. OPERATOR PREREQUISITE: create the `apparently-law` repo + Vercel project + Supabase project and register the project + deployment bindings in the orchestrator before activation.)

TWO DISTINCT THINGS — do not conflate (strategy doc Part 4.3):
- **Apparently Law = our own first-party sister law firm.** An entity we own/operate; we handle legal tasks/matters through it. It is the default escalation destination and the network anchor. THIS PROMPT builds Apparently Law's own site.
- **Apparently OS = the practice operating system OTHER lawyers use to launch and run their own independent boutique firms.** Boutiques are CUSTOMERS of Apparently OS (their firm runs on it), NOT part of Apparently Law. Apparently OS is a separate product surface (build it inside the Apparently app, reusing multi-entity + Vigil-lifecycle + fleet machinery — see the note in section 3 and the apparently-vigil-merge prompt; it is NOT part of this apparently-law repo).

Vision: Apparently Law is the FIRST option for legal escalation across the portfolio. Apparently OS boutiques are secondary referral capacity (especially out-of-expertise matters); Skadden/big-firm is tier-3 expansion. Token/subscription pricing kills hourly billing across both Apparently Law services and Apparently OS boutique plans.

## 1. Site + brand
- New Nuxt 3/4 + Supabase + Vercel + Tailwind app using the shared ht-ui design system (same source as apparently/packages/ht-ui — vendor or package-dep it; match Apparently's branding/styling exactly with an "Apparently Law" wordmark variant). Public pages: home (positioning: the AI-native law layer of Apparently), practice areas (gaming/CFTC first, then fintech/MSB/SEC/OCC/FDIC/FinCEN per the beachhead sequence), pricing (the public token price list — transparency IS the marketing), boutique network (join/apply), engage flow. Follow apparently conventions: strict TS, Zod inputs, RLS default-deny, ai-call-logger, selectModel().
- Proof: `npm run typecheck` clean; Playwright smoke on all public pages; a visual token check that ht-ui variables match Apparently's.

## 2. Shared identity + sync with Apparently (connected, fully synced, cross-branded)
- SSO with Apparently: extend the handoff-JWT pattern into a sustained shared session (same Supabase auth org linkage pattern as the smarter integration; secret `APPARENTLY_LAW_SHARED_SECRET`). S2S sync (HMAC): matters, escalations, findings (an Apparently finding escalates into an Apparently Law matter with full context), status back-sync so the Apparently risk register shows matter progress. Cross-branding: Apparently surfaces "Escalate to Apparently Law" as the default escalation CTA everywhere `schedule-consult`/attorney-network appears today.
- Proof: s2s tests (sign/verify/replay); escalation round-trip test with mocked Apparently.

## 3. First-option routing + referral relationship to Apparently OS boutiques
- Routing hierarchy in the match engine (port/extend apparently's attorney-network/match-engine.ts rather than duplicating): (1) Apparently Law (OUR firm) — always first when in scope + conflict-clear; (2) Apparently OS boutiques — independent firms running on Apparently OS, matched for capacity + out-of-expertise referrals with promoted placement + instant conflict-checked matching (a REFERRAL relationship — we do not own these firms); (3) big-firm tier (Skadden et al.) for bet-the-company matters. Conflict checks reuse apparently's coi-checker engines via S2S.
- IMPORTANT SCOPE BOUNDARY: this repo builds Apparently Law's site + the routing/referral consumer. It does NOT build Apparently OS (the launch-and-run-your-firm product) — that is a surface inside the Apparently app (built via the apparently-vigil-merge prompt's multi-entity + lifecycle + fleet machinery). This site only CONSUMES the OS boutique directory (via S2S) for tier-2 routing. Boutique onboarding/provisioning lives in Apparently OS, not here.
- Instrument referral flow both directions (Apparently Law overflow → OS boutiques; boutique out-of-scope → Apparently Law).
- Proof: routing tests (in-scope → tier 1 Apparently Law; conflict → tier 2 best OS-boutique match via mocked directory; bet-the-company flag → tier 3).

## 4. Token pricing = metered burn, NOT fixed quotes (operator round 3 correction; strategy 4.3/5.1)
- Pricing is metered token BURN exactly like normal AI usage — no fixed per-matter quote, no refund logic. Per-task cost is intentionally uncertain in advance (same as any prompt). Build: token ledger (purchase/burn/balance, per-org, RLS), subscription plans + Stripe metering for token top-ups, per-model + per-service burn rates, burn attribution per matter, invoices that show token consumption — never hours, never a quote.
- Apparently-Law human work = the SAME burn with a PREMIUM MULTIPLIER stacked on the token cost (mechanically like a pricier model costing more tokens per call — e.g. a `apparently_law_review` rate tier). "Get human counsel" is just "run at the Apparently-Law rate," which burns more. No separate hourly path.
- Margin: route deep swarm research/follow-up analysis to LOCAL/free models so the visible burn stays far below competitor cost while profitable (wire the local-model path; document the routing).
- DO NOT build: outcome-priced matters, fixed quotes, or refunds (explicitly removed per operator).
- Public rate card page: base rate, Apparently-Law premium multiplier, per-model rates. If a matter is instead outsourced to the attorney network, show the projected billable-rate estimate next to the in-house token cost at decision time.
- Credits interop hook: accept Smarter hive-contribution credits as token top-ups (envelope/API contract only this pass).
- Proof: ledger invariant tests (no negative balances, idempotent burns, premium-multiplier applied on the law-review tier); rate-card renders; local-model routing exercised in a burn test.

## 5. Compliance guardrails in-product
- Engagement scoping, UPL-safe jurisdiction gating (matter intake collects jurisdiction; out-of-license matters auto-route to the network), conflict workflow before any matter opens, privilege-aware storage (RLS + the pii-crypto patterns from apparently), and an audit trail on every routing decision (who/why/tier) — attribution rules apply.
- Proof: intake blocks unlicensed-jurisdiction direct engagement (routes to network instead); audit rows written on every route.
