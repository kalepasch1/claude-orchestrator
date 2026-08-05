# pareto-2080: PARETO TREASURY — the personal-CFO layer with embedded Tomorrow hedging

SUBMITTED-BY: kalepasch@gmail.com (operator decision 2026-08-04)

ACTIVATED 2026-08-04 by operator decision — the Wave-0 review gate this was held on now exists (commit a8ee6e3f, madeus.cc/waves).


ORIGINALLY-SUBMITTED-BY: kale@smrter.us (operator) 2026-07-28. Strategy: PORTFOLIO_STRATEGY_V2 Part 11.6 + 12.5b.

WORKFLOW: governed_heavy

NAMING (corrected round 9): this product is **"Pareto Treasury"** — the INDIVIDUAL/HNW twin, on Pareto ("treasury" reads private-bank/aspirational; do not use "Pareto Risk"). It is distinct from **Apparently Treasury**, which is the BUSINESS risk-management tab inside Apparently OS (separate prompt). Same engine underneath, different audiences and skins.

Pareto Treasury = a personal-CFO layer surfaced as a first-class tab: very easy to use/follow/implement.
1. Compose the existing engines into one Treasury surface: personal treasury/cash-yield (personalTreasury), tax-shape of the member's year (tax-swarm S2S), estate/liquidity events (estate module), the Standing, and the protection graph.
2. FULLY-EMBEDDED Tomorrow hedging in consumer-simple UX: for each detected exposure (income, equity concentration, rate, key-person, estate liquidity) render one card: plain-language risk → one-tap "Protect this" → licensed-rail product (standby / DCC/DSA per the credit-rails-v2 spec) with the fee shown like a subscription. Member NEVER sees a swap term sheet; all counsel/live-money flags default-OFF (mock rail until live).
3. Expert escalation rung: complex margins (offshore tax/estate-grade questions) route to Wealth-network experts (token-priced) when that network exists; stub the routing now.
4. RIA-election awareness (11.3): portfolio-level ADVICE features ship dark behind an `RIA_ENABLED` flag — copy stays education/planning until the operator elects registration.
Proof: Treasury tab renders all panels from fixtures; one-tap protect flow reaches the mocked rail with the fee-as-subscription framing; RIA-gated features dark by default; typecheck clean.
