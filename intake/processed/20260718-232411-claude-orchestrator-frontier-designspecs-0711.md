PROJECT: claude-orchestrator

# Design-spec batch (docs for human review, NOT code) for the frontier items that touch money movement, execution
# posture, privacy law, or the loop's objective — these must NOT be auto-merged as code. Each proof = the doc exists
# with the required sections (same pattern as designspec-cross-app-method-library). Every doc MUST include a
# "UI/UX embedding" section specifying how the feature meshes with the OS patterns (5/95 determination tiles, autonomy
# cockpit, approvals concierge, Studio-lane brand-kit, command-palette/sidebar, @ht/ui design tokens) and a
# "Posture preservation" section (per-app legal/regulatory guards stay intact).

- id: designspec-bonded-autonomy
  title: Design spec — bonded autonomy (warranty-backed guarantee on autonomous actions)
  material: no
  model: opus
  depends: []
  proof: `test -f docs/DESIGN_bonded_autonomy.md && grep -qi "underwriting" docs/DESIGN_bonded_autonomy.md && grep -qi "ui/ux" docs/DESIGN_bonded_autonomy.md && grep -qi "posture" docs/DESIGN_bonded_autonomy.md`
  prompt: |
    Write docs/DESIGN_bonded_autonomy.md. Design how the system underwrites its own autonomous actions ("we verified
    this; if it fails we cover the loss"), pricing the bond off the EXISTING primitives: reliability-priced warranty
    (apparently computeWarranty), proof-carrying + DecisionReceipt, outcome calibration, and the trust frontier. Required
    sections: underwriting model + capital reserve/escrow; which action classes are eligible (start: elder-fraud vendor
    verification, negotiation outcomes) and hard exclusions; claims/dispute flow; per-app posture preservation (Pareto
    non-custodial/free stays intact — bonding cannot introduce a fee/custody path there); UI/UX embedding (how the
    guarantee + its price + proof render on the 5/95 tile and approvals surface); regulatory/counsel gates
    (insurance-product implications); staged rollout + kill-switch. Flag every point needing a human/counsel decision.

- id: designspec-certified-execution-lanes
  title: Design spec — certified last-mile execution lanes (generalize session-rail across apps)
  material: no
  model: opus
  depends: []
  proof: `test -f docs/DESIGN_certified_execution_lanes.md && grep -qi "posture" docs/DESIGN_certified_execution_lanes.md && grep -qi "ui/ux" docs/DESIGN_certified_execution_lanes.md`
  prompt: |
    Write docs/DESIGN_certified_execution_lanes.md. Design how to generalize Pareto's session-rail (prepare -> stop at
    Submit -> human commits) into per-domain, counsel-CERTIFIED execution lanes across apps so approved actions actually
    complete (send/file/negotiate-live) WITHIN posture — the gap between "prepares everything" and "does everything."
    Required sections: the lane certification bar (what counsel must sign per domain before a lane can execute);
    reversibility + confidence gating (only certified + reversible + high-confidence + within-authority actions execute;
    everything else stays prepare-only); the "CADE determines / approval acts" doctrine preserved; per-app posture
    guards; kill-switch + audit (DecisionReceipt on every executed action); UI/UX embedding (how a "certified lane"
    action is visually distinct on the approvals/cockpit surface and how the user grants/revokes lane authority);
    incident/rollback. This is the highest-value + highest-risk unlock — bias conservative. Flag all counsel decisions.

- id: designspec-cross-tenant-federation
  title: Design spec — cross-tenant data network effect (privacy-preserving federated learning)
  material: no
  model: opus
  depends: []
  proof: `test -f docs/DESIGN_cross_tenant_federation.md && grep -qi "privacy" docs/DESIGN_cross_tenant_federation.md && grep -qi "ui/ux" docs/DESIGN_cross_tenant_federation.md`
  prompt: |
    Write docs/DESIGN_cross_tenant_federation.md. Design how each customer's outcomes improve every other customer's
    results WITHOUT exposing data, building on Tomorrow's DP/secure-aggregate privacy budget + the precedent index +
    fraud fingerprints. Required sections: what is shared (hashed fingerprints / DP-aggregated gradients, never raw
    data) vs never; the privacy budget accounting + guarantees; tenant isolation preservation; the network-effect
    flywheel + how it becomes lock-in; opt-in/consent + regulatory posture; UI/UX embedding (how a user sees "the
    network protected you" without any cross-tenant leakage); abuse/poisoning resistance. Flag counsel/privacy decisions.

- id: designspec-objective-function-governance
  title: Design spec — curating + guarding the self-improvement loop's objective function
  material: no
  model: opus
  depends: []
  proof: `test -f docs/DESIGN_objective_function_governance.md && grep -qi "goodhart" docs/DESIGN_objective_function_governance.md && grep -qi "ui/ux" docs/DESIGN_objective_function_governance.md`
  prompt: |
    Write docs/DESIGN_objective_function_governance.md. Now that the fleet proposes its own roadmap (EV-gated), design
    how the owner defines, versions, and GUARDS the global objective the loop optimizes — against Goodhart/reward-hacking
    and posture erosion. Required sections: the objective's components + weights + who can change them; anti-gaming
    guardrails (compliance-as-tests as hard constraints the objective can never trade away; canary metrics that detect
    reward-hacking); the "brief-don't-approve" governance amendment formalized; a change-review/versioning process;
    UI/UX embedding (an objective-and-guardrails cockpit showing what the loop is optimizing and any drift); rollback.
    This is the quiet 500x — the loop is only as good as the objective it serves. Flag every owner decision.

- id: designspec-comms-posture-legal-radar
  title: Design spec — register the comms/OS regulatory posture into Legal Radar (docs-as-code)
  material: no
  model: sonnet
  depends: []
  proof: `test -f docs/DESIGN_comms_posture_legal_radar.md && grep -qi "tcpa" docs/DESIGN_comms_posture_legal_radar.md && grep -qi "posture-compliance" docs/DESIGN_comms_posture_legal_radar.md`
  prompt: |
    Write docs/DESIGN_comms_posture_legal_radar.md. Design how the communications-OS regulatory posture (TCPA consent +
    universal opt-out, two-party recording disclosure, AI-voice disclosure, 10DLC brand/campaign, WhatsApp opt-in,
    Google Voice user-commissioned/agency model) is registered into Legal Radar as drift-detected docs-as-code AND
    mapped to a posture-compliance test suite (compliance.manifest.json merge gate) once the comms channels exist.
    Required sections: the doc set + owners; the machine-checkable invariants each maps to; how Legal Radar drift alerts
    route to counsel in minutes; UI/UX embedding (how consent/disclosure state surfaces to the user at call/send time);
    dependency on the CPaaS/channel OPERATOR items. This makes the plan's biggest cost (regulatory) nearly free.

OPERATOR:
  - All five are design docs for human review; the actual builds are separate, staged, approval-gated initiatives. None may weaken a per-app legal/regulatory posture guard.
  - Bonded autonomy + certified execution lanes require counsel sign-off before any implementation intake is queued.
