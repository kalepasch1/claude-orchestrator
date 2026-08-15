PROJECT: tomorrow

# Design-spec batch for the money/execution/posture-touching items — DOCS for human+counsel review, NOT code, because
# for Tomorrow these directly implicate the load-bearing posture (bilateral-only, ECP, no mutualization). Each proof =
# the doc exists with the required sections. Every doc MUST include a "Posture preservation" section proving it cannot
# create an order-book/auto-execute/mutualization path, and a "UI/UX embedding" section (5/95 tiles, war-room, cockpit).

- id: designspec-tomorrow-bonded-autonomy
  title: Design spec — bonded/warranty-backed autonomous actions for Tomorrow (ECP-safe)
  material: no
  model: opus
  depends: []
  proof: `test -f docs/DESIGN_tomorrow_bonded_autonomy.md && grep -qi "posture" docs/DESIGN_tomorrow_bonded_autonomy.md && grep -qi "ui/ux" docs/DESIGN_tomorrow_bonded_autonomy.md && grep -qi "ecp" docs/DESIGN_tomorrow_bonded_autonomy.md`
  prompt: |
    Write docs/DESIGN_tomorrow_bonded_autonomy.md. Design a warranty/proof-backed guarantee on eligible autonomous
    outputs (e.g., a verified hedge recommendation), pricing the bond off verifiableProof + reliability calibration.
    Required sections: eligible action classes + hard exclusions (nothing that would imply price formation, execution,
    mutualization, or a DCO-like structure); how bonding stays inside the bilateral/ECP posture (no custody, named legs
    only); capital/reserve model; claims/dispute flow; UI/UX embedding (bond price + coverage + proof on the 5/95 tile);
    counsel/regulatory gates (financial-product + CFTC implications). Flag every counsel decision. No code.

- id: designspec-tomorrow-execution-lane
  title: Design spec — certified prepare-to-commit lane (NO auto-execute; bilateral posture preserved)
  material: no
  model: opus
  depends: []
  proof: `test -f docs/DESIGN_tomorrow_execution_lane.md && grep -qi "no order book" docs/DESIGN_tomorrow_execution_lane.md && grep -qi "posture" docs/DESIGN_tomorrow_execution_lane.md && grep -qi "ui/ux" docs/DESIGN_tomorrow_execution_lane.md`
  prompt: |
    Write docs/DESIGN_tomorrow_execution_lane.md. Design how far the "last mile" can go for Tomorrow WITHOUT breaching
    posture: the lane may prepare, package, sign (DecisionReceipt), and route a bilateral IOI to a named ECP
    counterparty for a HUMAN to commit — it may NEVER auto-match, create an order book, form price, or click-to-execute.
    Required sections: an explicit "No order book / no click-to-execute" section restating the §2(h)(7) boundary and how
    the design provably stays inside it (ties to postureInvariants); the certification bar counsel must sign per lane;
    reversibility + ECP + within-authority gates; UI/UX embedding (how a "prepared, awaiting your commit" IOI renders vs
    a normal card); kill-switch + audit. Bias maximally conservative. Flag every counsel decision. No code.

OPERATOR:
  - Both are design docs for human + counsel review. No implementation intake may be queued until counsel signs the posture analysis — especially the execution-lane boundary.
