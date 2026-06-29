PROJECT: hisanta

- id: darwin-vendor
  title: Vendor @darwin/kernel into the repo (additive)
  material: no
  model: haiku
  depends: []
  proof: `node --experimental-strip-types -e "import('./vendor/darwin-kernel/src/governance/index.ts').then(m=>process.exit(m.governAction?0:1))"` exits 0
  prompt: |
    Copy packages/darwin-kernel/src from the orchestrator repo (env ORCHESTRATOR_REPO,
    default ../beethoven/claude-orchestrator) into vendor/darwin-kernel/src, EXCLUDING
    cade/. Add vendor/darwin-kernel/package.json. Integration points: lib/ + supabase/ edge
    functions. Do not import it yet. See DARWIN_KERNEL_ADOPTION.md in this repo.

- id: darwin-parent-gate-constitution
  title: Model the parent-approval gate as a kernel constitution + receipts
  material: yes
  model: sonnet
  depends: [darwin-vendor]
  proof: `node --experimental-strip-types --test lib/__tests__/darwinGate.test.ts` exits 0
  prompt: |
    Make the existing parent-approval posture explicit and auditable (additive — this only
    adds signed receipts; existing santa_message_status flow stays).
    Steps:
    1. Build hisanta.hisantaConstitution() (escalate deliver_ai_message / open_loot_box /
       gift_purchase; deny charge_child / open_ended_child_chat).
    2. Before any child-facing AI message is shown, call governAction(); 'escalate' routes
       to the existing parent-approval queue. Persist receipts to darwin_receipts (fail-soft)
       so the parent-visibility surface shows a verifiable trail.
    3. Add test lib/__tests__/darwinGate.test.ts asserting charge_child → deny and
       deliver_ai_message → escalate, with verifyReceipt true.

- id: darwin-guardian-claim-edges
  title: Emit guardian_verified claim + link the child node (generational fabric)
  material: yes
  model: sonnet
  depends: [darwin-parent-gate-constitution]
  proof: `node --experimental-strip-types --test lib/__tests__/darwinHousehold.test.ts` exits 0
  prompt: |
    On guardian verification, emit a passport claim and a household edge so the family graph
    connects to Pareto household/college planning later. NO child PII — opaque subject ids only.
    Steps:
    1. Build a passport with hisanta.hisantaGuardianClaim() for the guardian subject
       (deriveSubject) and persist it (darwin_passports).
    2. Write a guardian_of identity edge {from: guardianSubject, to: childSubject} to
       darwin_identity_edges.
    3. Add test lib/__tests__/darwinHousehold.test.ts that builds the household rollup
       (householdRollup) and asserts guardian + child appear with the union of products and
       that no raw child PII is serialized into the edge/claim.

- id: darwin-publish-capabilities
  title: Publish character_ledger + adaptive_difficulty capabilities
  material: no
  model: sonnet
  depends: [darwin-vendor]
  proof: `node --experimental-strip-types --test lib/__tests__/darwinCapabilities.test.ts` exits 0
  prompt: |
    Publish hisanta.hisantaCapabilities so the per-child trait ledger and the adaptive
    difficulty engine are reusable (e.g. Pareto financial-literacy gamification).
    Steps:
    1. Map each capability endpoint to the existing route/edge function.
    2. Publish the specs (seed) and add test darwinCapabilities.test.ts that publishes +
       instantiates character_ledger against a stub handler.

OPERATOR:
  - Apply vendor/darwin-kernel/sql/0001_darwin_kernel.sql to the Hisanta Supabase project (use the SHARED project so guardian passports/edges are portable).
  - Set DARWIN_SIGNING_PRIVATE_KEY_PEM in the Hisanta host/edge env (shared portfolio anchor).
