PROJECT: smarter

- id: darwin-vendor
  title: Vendor @darwin/kernel into the repo (additive)
  material: no
  model: haiku
  depends: []
  proof: `node --experimental-strip-types -e "import('./vendor/darwin-kernel/src/governance/index.ts').then(m=>process.exit(m.governAction?0:1))"` exits 0
  prompt: |
    Copy packages/darwin-kernel/src from the orchestrator repo (env ORCHESTRATOR_REPO,
    default ../beethoven/claude-orchestrator) into vendor/darwin-kernel/src, EXCLUDING
    cade/. Add vendor/darwin-kernel/package.json ({"name":"@darwin/kernel","type":"module",
    "main":"./src/index.ts"}) and `"@darwin/kernel":"file:vendor/darwin-kernel"` to deps.
    Do not import it yet. See DARWIN_KERNEL_ADOPTION.md in this repo.

- id: darwin-constitution-gate
  title: Make the pre-send / UPL gate a kernel constitution
  material: yes
  model: sonnet
  depends: [darwin-vendor]
  proof: `npx vitest run server/utils/__tests__/darwinPolicy.test.ts` exits 0
  prompt: |
    Replace the bespoke pre-send/UPL policy check with the kernel constitution so the gate
    is provable and portfolio-consistent (additive — keep the global auto-send kill-switch).
    Steps:
    1. Build a smarter constitution via smarter.smarterConstitution() from
       @darwin/kernel/products (deny render_legal_advice; escalate final send;
       allow drafting/classify).
    2. Route the pre-send review through governAction(); on 'deny' block the send, on
       'escalate' require human approval, on 'allow' proceed. Persist the receipt to
       darwin_receipts (fail-soft).
    3. Add test darwinPolicy.test.ts asserting render_legal_advice → deny and a final
       send_to_counterparty_final action → escalate.

- id: darwin-publish-capabilities
  title: Publish Smarter deal-intelligence engines as capabilities
  material: no
  model: sonnet
  depends: [darwin-vendor]
  proof: `npx vitest run server/utils/__tests__/darwinCapabilities.test.ts` exits 0
  prompt: |
    Publish obligation_extraction, negotiation_position, time_estimate, contact_enrichment
    (smarter.smarterCapabilities) so Tomorrow's War Room can instantiate them rather than
    rebuilding them.
    Steps:
    1. Add server/utils/darwin/capabilities.ts mapping each capability endpoint to the
       existing route/handler in this repo.
    2. Add a startup seed that publishes the specs.
    3. Add test darwinCapabilities.test.ts that publishes + instantiates obligation_extraction
       against a stub handler and asserts a typed result.

- id: darwin-reliability-claim
  title: Emit a counterparty reliability passport claim
  material: no
  model: sonnet
  depends: [darwin-vendor]
  proof: `npx vitest run server/utils/__tests__/darwinReliability.test.ts` exits 0
  prompt: |
    From the existing sender-profile reliability score, mint a kernel passport claim that
    Tomorrow's credit index can consume.
    Steps:
    1. Where sender/counterparty reliability is computed, build a passport with
       smarter.smarterReliabilityClaim(score) and persist it (darwin_passports).
    2. Add test darwinReliability.test.ts asserting verifyPassport(passport).valid === true
       and hasClaim(passport,'reliability', 0) === true.

OPERATOR:
  - Apply vendor/darwin-kernel/sql/0001_darwin_kernel.sql to the Smarter Supabase project.
  - Set DARWIN_SIGNING_PRIVATE_KEY_PEM in the Smarter host env (shared portfolio anchor).
  - Separate (non-kernel) blocker owned elsewhere: the hardcoded @ht/ui absolute-path alias still breaks CI on other machines.
