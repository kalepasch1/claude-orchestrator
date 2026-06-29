PROJECT: apparently

- id: darwin-vendor
  title: Vendor @darwin/kernel into the repo (additive)
  material: no
  model: haiku
  depends: []
  proof: `node --experimental-strip-types -e "import('./vendor/darwin-kernel/src/governance/index.ts').then(m=>process.exit(m.governAction?0:1))"` exits 0
  prompt: |
    Copy packages/darwin-kernel/src from the orchestrator repo (env ORCHESTRATOR_REPO,
    default ../beethoven/claude-orchestrator) into vendor/darwin-kernel/src, EXCLUDING
    cade/. Add vendor/darwin-kernel/package.json and `"@darwin/kernel":"file:vendor/darwin-kernel"`
    to deps. Do not import it yet. See DARWIN_KERNEL_ADOPTION.md in this repo.

- id: darwin-govern-bots
  title: Govern the disclosure/opinion bots with the kernel constitution
  material: yes
  model: sonnet
  depends: [darwin-vendor]
  proof: `npx vitest run server/__tests__/darwinGovern.test.ts` exits 0
  prompt: |
    Wrap the disclosure/legal-opinion bots in governAction (additive). Matches the existing
    grounding rule: every assertion cites a source or is not asserted.
    Steps:
    1. Build a constitution via apparently.apparentlyConstitution() (escalate
       publish_legal_opinion / file_regulatory_submission; deny assert_without_citation).
    2. Before a bot publishes an opinion or files, call governAction(); block on deny,
       human-approve on escalate. Persist receipts to darwin_receipts (fail-soft).
    3. Add test darwinGovern.test.ts asserting assert_without_citation → deny and
       publish_legal_opinion → escalate.

- id: darwin-publish-legal-capabilities
  title: Publish regulator-intel / legal-opinion / licensing capabilities
  material: no
  model: sonnet
  depends: [darwin-vendor]
  proof: `npx vitest run server/__tests__/darwinCapabilities.test.ts` exits 0
  prompt: |
    Make Apparently the portfolio's legal/regulatory backbone by publishing
    apparently.apparentlyCapabilities (regulator_intel, legal_opinion, licensing_check) so
    Tomorrow/Galop/Smarter consume them.
    Steps:
    1. Add server/utils/darwin/capabilities.ts mapping each capability endpoint to the
       existing route (regulator-intel query, legal-opinion draft, licensing check).
    2. Add a startup seed publishing the specs.
    3. Add test darwinCapabilities.test.ts that publishes + instantiates regulator_intel
       against a stub handler and asserts a typed result with citations.

OPERATOR:
  - Apply vendor/darwin-kernel/sql/0001_darwin_kernel.sql to the Apparently Supabase project (RLS default-deny matches the new darwin_* tables).
  - Set DARWIN_SIGNING_PRIVATE_KEY_PEM in the Apparently host env (shared portfolio anchor).
