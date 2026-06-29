PROJECT: claude-orchestrator

# All tasks operate on packages/darwin-kernel (the shared @darwin/kernel) and, for the
# G-series, the orchestrator runner/web. Kernel modules are pure, additive TypeScript with
# node:test gates. The kernel currently has 59 tests green + 0 typecheck errors; every task
# below must keep both true. Run the full suite after each:
#   cd packages/darwin-kernel && node --test --experimental-strip-types test/*.test.ts

- id: kernel-margin-aware-crosssell
  title: Rank cross-sell routes by realized margin (economics → suggestRoutes)
  material: no
  model: sonnet
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/crossSellEconomics.test.ts` exits 0
  prompt: |
    Feed realized economics back into cross-sell so routes are ranked by money, not static
    scores. Additive — current suggestRoutes behavior must be unchanged when no economics
    signal is passed.
    Steps:
    1. Add src/identity/crossSellEconomics.ts exporting rankRoutesByRealizedMargin(routes,
       signal) where routes come from identity/graph.suggestRoutes and signal is built from
       orchestratorClient/economics.productEconomics (and optionally identity/relationshipPnl).
       Re-rank: primary key = realized net/margin for the target product, tiebreak = the
       existing route.score.
    2. Re-export from src/identity/index.ts.
    3. Add test/crossSellEconomics.test.ts: a route to a product with higher realized margin
       outranks a route with a higher static score but lower margin; with an empty signal the
       order equals suggestRoutes().

- id: kernel-service-catalog-graph
  title: Capability service catalog + cross-product dependency graph
  material: no
  model: sonnet
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/serviceCatalog.test.ts` exits 0
  prompt: |
    From published CapabilitySpecs + signed UsageRecords, emit the who-calls-whose-engine
    graph for ops + the external developer-platform spec.
    Steps:
    1. Add src/orchestratorClient/serviceCatalog.ts exporting buildServiceCatalog(specs,
       usageRecords) -> { nodes: capability[], edges: {caller,owner,capabilityId,calls}[],
       topConsumed: capabilityId[], spofs: capabilityId[] }. A SPOF = an owner/capability that
       >1 distinct caller products depend on. Ignore tampered usage records (verifyUsageRecord).
    2. Re-export from src/orchestratorClient/index.ts.
    3. Add test/serviceCatalog.test.ts building a catalog from sample specs + usage and
       asserting the top-consumed capability and at least one SPOF are identified.

- id: kernel-receipt-projection
  title: Receipt-chain event-sourcing projection + replay
  material: no
  model: sonnet
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/projection.test.ts` exits 0
  prompt: |
    Generalize verifyChain into a replayable projection so the receipt log doubles as an
    event-sourcing spine + DR replay.
    Steps:
    1. Add src/governance/projection.ts exporting replayChain(receipts, reducer, initial) that
       verifies the chain (reusing verifyChain) THEN folds receipts into derived state, and
       chainStats(receipts) -> { count, byDecision, firstAt, lastAt, ok, brokenAt }.
       replayChain must throw/return a typed error if the chain is broken or reordered.
    2. Re-export from src/governance/index.ts.
    3. Add test/projection.test.ts: replay a valid chain to an expected derived state; assert a
       reordered/tampered chain is rejected.

- id: kernel-evidence-bundle
  title: Compliance + judgment "exhaust" export bundle (regulator-facing data product)
  material: no
  model: sonnet
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/evidenceBundle.test.ts` exits 0
  prompt: |
    One call that assembles a PolicyService CompliancePack + selected attestation-feed entries
    into a single signed, offline-verifiable evidence bundle.
    Steps:
    1. Add src/governance/evidenceBundle.ts exporting buildEvidenceBundle({ product, pack,
       attestations }) -> content-addressed + digest over {pack, attestations}, and
       verifyEvidenceBundle(bundle) that re-verifies the pack (verifyCompliancePack), every
       attestation (verifyAttestation), and the bundle digest — fully stateless.
    2. Re-export from src/governance/index.ts (or a new src/index.ts line).
    3. Add test/evidenceBundle.test.ts: build a bundle from a real PolicyService pack + two
       attestations, assert verifyEvidenceBundle valid, and that tampering any attestation or
       receipt fails verification.

- id: kernel-govern-cli
  title: govern-cli + wire the orchestrator runner's own approvals through the kernel
  material: yes
  model: opus
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/governCli.test.ts` exits 0
  prompt: |
    Make the orchestrator dogfood the kernel: every MATERIAL change it approves gets a signed,
    chained, offline-verifiable receipt. The runner is Python and the kernel is TS, so bridge
    via a small CLI (no Python port).
    Steps:
    1. Add packages/darwin-kernel/bin/govern-cli.ts: `mint` reads a JSON action (+ optional
       prevReceipt) on stdin and prints a receipt JSON (governAction with a default
       orchestrator constitution where approve/merge of material changes escalates);
       `verify` reads a receipt JSON and exits 0/1 via verifyReceipt.
    2. Wire runner approval: when a material task is approved (runner/ approval path), shell out
       `node --experimental-strip-types packages/darwin-kernel/bin/govern-cli.ts mint` and store
       the receipt (a darwin_receipts row or runner/receipts/*.json). Fail-soft: never block a
       merge if the CLI is unavailable, but log it.
    3. Add test/governCli.test.ts driving the CLI mint→verify round-trip and a tamper-fails case.
    NOTE: this touches the orchestrator's own approval path — keep it in the human-approval lane.

- id: kernel-public-verifier
  title: Public verifier endpoint (productize stateless verification)
  material: yes
  model: sonnet
  depends: [kernel-govern-cli]
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/verifyCli.test.ts` exits 0
  prompt: |
    Expose offline verification of any receipt / passport / attestation / compliance-pack /
    evidence-bundle as a service — the sellable trust surface.
    Steps:
    1. Add packages/darwin-kernel/bin/verify-cli.ts: reads a pasted envelope JSON (auto-detects
       kind) and prints { valid, reason }; exits 0 when valid.
    2. Add a thin orchestrator web route (web/ Nuxt server route, e.g. /api/verify) that accepts
       a pasted envelope or an id and returns the verification result by calling the same
       verification functions. Public, read-only, no secrets (verification needs only the
       embedded public key).
    3. Add test/verifyCli.test.ts asserting a good artifact validates and a tampered one is
       rejected for each kind. Include a curl example in packages/darwin-kernel/README.md.

OPERATOR:
  - Register a `claude-orchestrator` project in the orchestrator's projects table if absent (name: claude-orchestrator, repo_path: /Users/kpasch/Documents/beethoven/claude-orchestrator) so intake can attach these tasks. If your intake only accepts the app-repo slugs, route this file manually.
  - Deploy the public verifier web route (kernel-public-verifier) to the orchestrator's Vercel web project once merged; set no secrets (verification is keyless by design).
  - The govern-cli wiring modifies the runner's own approval path — review before enabling in the live runner (it is fail-soft, so a missing CLI never blocks merges).
