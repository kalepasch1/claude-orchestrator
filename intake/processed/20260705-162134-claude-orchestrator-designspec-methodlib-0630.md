PROJECT: claude-orchestrator

# CROSS-REPO DESIGN-SPEC task (not implementation). Produce a design document a human reviews BEFORE
# any refactor. Output is a markdown doc; proof = the doc exists with the required sections. This is
# the higher-order moat: share optimization METHODS (algorithms), not just DATA (the oracle already
# shares data), across the sibling apps pareto-2080 / tomorrow / smarter / apparently.

- id: designspec-cross-app-method-library
  title: Design spec — shared optimization-method library across pareto/tomorrow/smarter/apparently
  material: no
  model: opus
  depends: []
  proof: `test -f docs/DESIGN_cross_app_method_library.md && grep -qi "versioning" docs/DESIGN_cross_app_method_library.md && grep -qi "posture" docs/DESIGN_cross_app_method_library.md`
  prompt: |
    Write docs/DESIGN_cross_app_method_library.md (in the claude-orchestrator repo — the cross-repo
    coordination hub). The oracle shares DATA across the siblings; this spec designs sharing METHODS:
    the same negotiation, mechanism-design (Myerson/Vickrey), Shapley/fairness allocation, digital-twin
    RL, market-graph/k-anon aggregation, verifiable-proof, and privacy (DP/secure-aggregate) cores exist
    in multiple repos and drift. A shared library means an improvement to the negotiation or
    mechanism-design core in ONE app instantly upgrades ALL of them.
    Required sections:
      1. Inventory — the reusable primitives that already exist in each repo (map them: pareto
         negotiationBandit/marketGraph/myersonAuction/twinNegotiator; tomorrow verifiableProof/
         privacyBudget/liquidityMining/fairness/riskFabric; smarter negotiation/QC; apparently
         intake-standard/position-engine) and where they overlap/diverge.
      2. Shared-package design — a language-appropriate shared module (npm workspace package or a
         vendored pure-core) of framework-agnostic PURE functions; what belongs in it vs stays app-local.
      3. Posture preservation (LOAD-BEARING) — each app has DIFFERENT legal/regulatory posture (pareto:
         free/non-adviser/non-custodial; tomorrow: ECP/bilateral/CFTC; apparently: legal/UPL). The shared
         methods must be POSTURE-NEUTRAL primitives; posture guards stay per-app. Specify how the library
         stays neutral and how each app injects its own guards.
      4. Versioning + governance — semver, a golden-vector contract test so identical logic stays
         byte-identical across apps (tomorrow already uses this pattern), and how a change propagates.
      5. Distribution — how each repo consumes it under the orchestrator's isolated-worktree model
         (vendoring vs package registry; keeping the "no cross-repo runtime coupling" property).
      6. Migration plan — incremental (start with 1-2 primitives), never a big-bang; how to prove
         parity before switching an app over.
      7. Risks — the cost of coupling (a bug propagates everywhere) and mitigations (contract tests,
         staged rollout, per-app override).
    Keep it a spec; no production code / no refactor yet. Flag every point that needs a human decision.

OPERATOR:
  - Design doc for human review only. The actual shared-library extraction is a separate, staged initiative gated on approval — it must NOT weaken any app's per-app legal/regulatory posture guards.
