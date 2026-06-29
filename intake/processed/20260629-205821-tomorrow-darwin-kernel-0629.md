PROJECT: tomorrow

- id: darwin-vendor
  title: Vendor @darwin/kernel into the repo (additive)
  material: yes
  model: sonnet
  depends: []
  proof: `node --experimental-strip-types -e "import('./vendor/darwin-kernel/src/governance/index.ts').then(m=>process.exit(m.governAction?0:1))"` exits 0
  prompt: |
    Vendor the shared kernel so Tomorrow can adopt it. CAUTION: this repo auto-merges to
    prod via the self-improvement loop — keep the diff minimal and additive.
    Steps:
    1. Copy packages/darwin-kernel/src from the orchestrator repo (env ORCHESTRATOR_REPO,
       default ../beethoven/claude-orchestrator) into vendor/darwin-kernel/src, EXCLUDING
       the cade/ subdir. Add a vendored vendor/darwin-kernel/package.json
       ({"name":"@darwin/kernel","type":"module","main":"./src/index.ts"}).
    2. Add `"@darwin/kernel": "file:vendor/darwin-kernel"` to package.json deps.
    3. Do not import it anywhere yet (no behavior change). See DARWIN_KERNEL_ADOPTION.md.

- id: darwin-constitution-delegate
  title: Delegate evaluateConstitution to the kernel + emit shared receipts
  material: yes
  model: opus
  depends: [darwin-vendor]
  proof: `npx vitest run server/utils/policy/__tests__/darwinReceipt.test.ts` exits 0 AND `npm run lint:migrations` clean
  prompt: |
    Make Tomorrow emit the portfolio-standard signed receipt format WITHOUT changing its
    hard gates. This is policy-core + prod-auto-merge: minimal, additive, fail-closed.
    Steps:
    1. In server/utils/policy/enforce.ts, after the existing evaluateConstitution result,
       also call governAction() from @darwin/kernel/governance to mint a signed,
       hash-chained receipt for the action, and persist it to darwin_receipts (append-only,
       fail-soft if table absent). Keep the EXISTING decision authority — ECP gate,
       SWAP_ONLY allowlist, bilateral-only, disinterested-operator stay enforced in code as
       locked dimensions; the kernel must never loosen them.
    2. Set the kernel trust anchor from the existing key: read
       PROOF_SIGNING_PRIVATE_KEY_PEM and pass it as DARWIN_SIGNING_PRIVATE_KEY_PEM (env
       alias) so receipts verify against the same anchor as C1 proofs.
    3. Add test server/utils/policy/__tests__/darwinReceipt.test.ts asserting a governed
       action yields a verifyReceipt-valid receipt and that a §1a action (money_move)
       escalates.

- id: darwin-publish-capabilities
  title: Publish Tomorrow capabilities to the shared registry
  material: yes
  model: sonnet
  depends: [darwin-constitution-delegate]
  proof: `npx vitest run server/utils/darwin/__tests__/capabilities.test.ts` exits 0
  prompt: |
    Publish Tomorrow's engines so other products can instantiate them (metered).
    Steps:
    1. Create server/utils/darwin/capabilities.ts that imports tomorrow.tomorrowCapabilities
       from @darwin/kernel/products and maps each capability endpoint to the existing route
       (price_swap → /api/otc/price; parametric_displacement → /api/risk/studio/displace;
       war_room_pipeline → the war-room ingest route; fabric_run → /api/otc/fabric/run).
    2. Add a startup seed (server plugin) that publishes the specs to the registry transport.
    3. Add test capabilities.test.ts that publishes the specs and instantiates price_swap
       against a stub handler, asserting a typed result.

- id: darwin-passport-instant-underwrite
  title: Issue ECP/credit passport claims + instant-underwrite via runFlywheel
  material: yes
  model: sonnet
  depends: [darwin-constitution-delegate]
  proof: `npx vitest run server/utils/darwin/__tests__/flywheel.test.ts` exits 0
  prompt: |
    Close the cross-product underwriting funnel for Risk Studio.
    Steps:
    1. On ECP-gate pass / credit-index computation, build a kernel passport with
       tomorrow.tomorrowEcpClaim() + tomorrow.tomorrowCreditClaim(compositeQuality) and
       persist it (darwin_passports).
    2. In the Risk Studio displacement intake, call runFlywheel({subject, asking:'tomorrow',
       passports, consent, alreadyOn}); when prefill.canInstantUnderwrite is true, skip the
       fresh KYC + financial intake and price directly.
    3. Add test flywheel.test.ts: a Galop kyc_verified passport + Pareto financial_profile
       claim (with consent grants) yields prefill.canInstantUnderwrite === true; without
       consent it is false. See DARWIN_KERNEL_ADOPTION.md Wire 3+4.

OPERATOR:
  - Apply vendor/darwin-kernel/sql/0001_darwin_kernel.sql to the Tomorrow Supabase project (darwin_receipts / darwin_passports / darwin_capabilities, RLS-enabled). Name-check per the migration rules before landing.
  - Confirm DARWIN_SIGNING_PRIVATE_KEY_PEM resolves to PROOF_SIGNING_PRIVATE_KEY_PEM in Vercel prod env so the shared anchor is stable.
  - These changes auto-merge to prod — keep them in the human-approval lane.
