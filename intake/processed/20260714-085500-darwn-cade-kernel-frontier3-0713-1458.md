PROJECT: darwn

# CADE kernel frontier-3 — the moat layer on top of the shipped @darwin/kernel/cade
# (credential.ts, federation.ts, finality.ts, capital.ts, doctrine.ts; ~181 kernel tests green).
# ENHANCE the named existing kernel modules; consume existing exports; nothing rebuilds.
# darwn is Nuxt+Prisma: `npm test` = vitest run, `npm run build` = nuxt build. Prefer a
# targeted new vitest spec as proof (keeps build green). Locate the kernel via the import
# tomorrow's frontier tasks already use (`@darwin/kernel/cade`).

- id: cadek-zk-privilege-proof
  title: Privilege-preserving (commitment/ZK) proof over a determination credential
  material: yes
  model: opus
  depends: []
  proof: `npx vitest run kernel/cade/__tests__/zk-credential.test.ts` exits 0 AND `npm run build` exits 0
  prompt: |
    ENHANCE @darwin/kernel/cade/credential.ts: add a privilege-preserving proof so a determination
    can be VERIFIED (valid + passed its gates + issuer identity) WITHOUT revealing the privileged
    legal basis (weakness ledger text, authorities, reasoning). Smallest viable: a commitment scheme
    — hash-commit the private basis, expose a signed public claim {determinationId, gatesPassed,
    tenabilityBand, issuer, commitment}, and `verifyRedacted(publicClaim)` that checks signature +
    gate flags without the basis; `openCommitment(basis)` proves the committed basis matches on
    demand (e.g. under a protective order). Round-trip + tamper + wrong-basis tests. This is the
    unlock for cross-FIRM federation (frontier-2 does cross-APP): you can share a verifiable
    determination without waiving privilege. Keep existing credential APIs unchanged (additive).

- id: cadek-market-bench
  title: Feed the challenge-market overturn price back as the Bench's P(win) prior
  material: yes
  model: sonnet
  depends: []
  proof: `npx vitest run kernel/cade/__tests__/market-bench.test.ts` exits 0 AND `npm run build` exits 0
  prompt: |
    Frontier-1 shipped bilateral challenge legs + market-implied overturn probability. ENHANCE the
    Bench/tenability path in @darwin/kernel/cade so the LIVE market-implied overturn price is
    blended into the Bench's P(win) prior (shrinking toward the market as liquidity/volume grows),
    making CADE's confidence continuously calibrated by people with money at stake. Pure blend
    function `blendMarketPrior(modelP, marketP, liquidity)` + wiring; do NOT change the golden-locked
    scoreTenability. Test: no market → model prior unchanged; deep market → tracks market; monotone
    in liquidity. Additive.

- id: cadek-federation-reputation
  title: Issuer reputation + staking on federated determinations
  material: yes
  model: opus
  depends: [cadek-zk-privilege-proof]
  proof: `npx vitest run kernel/cade/__tests__/federation-reputation.test.ts` exits 0 AND `npm run build` exits 0
  prompt: |
    ENHANCE @darwin/kernel/cade/federation.ts: add an issuer-reputation + staking layer so a
    consumer weights an accepted determination credential by the issuer's realized track record,
    and an issuer can STAKE on a determination (skin in the game) that is slashed on overturn.
    Pure ledger + scoring: `reputationOf(issuer, history)`, `applyStake(cred, amount)`,
    `settleStake(cred, outcome)`. Consume the existing verify/accept path (do not change its
    signature). Tests: reputation rises with held determinations + falls on overturns; a slashed
    stake reduces reputation; unstaked credentials still accepted but down-weighted. Turns
    federation from plumbing into a trust market — the network-effect moat.

OPERATOR:
  - Confirm the exact kernel path/test config for @darwin/kernel/cade (the executor resolves via tomorrow's existing import) and align the proof test path accordingly.
  - Any real staking/settlement of value is a human-approved, off-by-default capability — the kernel work here is calc-only ledger logic, no live funds.
