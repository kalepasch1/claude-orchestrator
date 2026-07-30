# v5 RECONCILIATION — enhance/extend existing code, do NOT rebuild

Operator direction 2026-07-09: much of v5 already exists in code or the queue. This file reclassifies every v5 item as ENHANCE-EXISTING (extend a named module) or NET-NEW, so the planner extends rather than duplicates. Supersedes decomposition instructions in PROMPT-v5-cade-reuse-selfimproving-testbots. Hard rule for the planner: for every ENHANCE item, the task must reference the existing file/module and be framed as "extend X to add Y" — a task that recreates an existing module fails review. Run intake dedup (G7) against CADE_IMPLEMENTATION_HANDOFF.md, ORCHESTRATOR_INTAKE_BACKLOG.md, cowork-backlog/backlog.json before queuing.

## Audit result summary
The shared `@darwin/kernel` (CADE engine, passport, identity graph, flywheel, governance, attestation) is ~80–90% built. Most v5 items are SURFACES/WIRING on top of existing primitives, or already-queued backlog tasks needing enhancement — NOT net-new builds. Zero items should be greenfield except where marked NET-NEW.

## §1 CADE Precedent Reuse — mostly ENHANCE existing CADE infra
- **P-1 memo store + fingerprint** — ENHANCE. Spec already exists (CADE_IMPLEMENTATION_HANDOFF §6.2 "standing-roster cache"); engine.ts already computes `cheapPositions`. Task = add the persistence layer + issue fingerprint index; do NOT re-architect the engine. Ref: packages/darwin-kernel/src/cade/engine.ts, HANDOFF §6.2/§3.
- **P-2 validity/staleness gate** — ENHANCE. Apparently already has `opinion-staleness-detector.ts`; reuse its pattern for CADE cache invalidation, wired to X2 oracle events. Do NOT build a new staleness concept from scratch. Ref: apparently/server/engines/.../opinion-staleness-detector.ts.
- **P-3 three-tier ladder** — ENHANCE engine.ts (add exact-reuse + warm-evolve paths around existing runDetermination); the recursive sub-question mechanism already exists — reuse it for delta re-determination.
- **P-4 lineage/provenance** — NET-NEW field on proof schema (add `parentDeterminationId` + inherited-subissue citations to ProofPack). Small, additive. Ref: packages/darwin-kernel/src/cade/certificate.ts.
- **P-5 cross-room compounding** — ENHANCE. Emerges from P-1..P-3; Tomorrow-side wiring only.
- **P-6 barrier siloing** — ENHANCE existing consent/identity graph (identity/graph.ts ConsentGrant) — reuse, don't rebuild.
- **Calibration flywheel** (was implied "new") — ENHANCE/COMPLETE. Persona.reliability field + flywheel.ts already exist; HANDOFF §3.4 spec exists. Task = implement the outcome→`cade_calibration`→reliability write-back per product. Explicitly NOT net-new. Ref: packages/darwin-kernel/src/flywheel.ts, cade/types.ts.

## §2 Cross-app coordination — ENHANCE existing kernel primitives (NOT new infra)
- Passport, identity graph, consent spine, flywheel ALREADY EXIST and work (passport.ts, identity/graph.ts, flywheel.ts). 
- **B-1 onboarding graph** — ENHANCE: build cluster-scoped prefill ON the existing identity graph — do not create a parallel graph.
- **B-2 wallet** — ENHANCE: surface over existing passport/flywheel entitlements.
- **B-3 persona registry** — ENHANCE: promote existing cade/types Persona defs into a shared kernel store; single-source the copies.
- **B-4 event fabric** — NET-NEW (thin): no centralized typed event schema found; build it as a schema+router over existing coordination bus/topics, reusing H3 projection for replay. Keep minimal.
- Cluster scoping (financial vs consumer) and B-5 value gate — NET-NEW policy, cheap.

## §3 Tomorrow contract engine — ENHANCE existing generator + already-queued tasks
- generatorV3.ts, instrumentFoundry.ts, payoffDSL.ts, allowlist compile ALREADY EXIST. Backlog already has `composite-payoff-compiler` (B9) and `instrument-discovery-loop` (B11) QUEUED.
- **CG-1 generative structuring** — ENHANCE generatorV3/instrumentFoundry + complete B9/B11 wiring (demand→generate→backtest→promote). Do NOT build a new generator.
- **CG-2 evolutionary fitness** — NET-NEW layer ON generatorV3 output (fitness scoring + guided search). Additive.
- **CG-3 adversarial self-play** — NET-NEW red-team engine, but must consume existing backtest + allowlist, not replace them.
- **CG-4 comprehension score / CG-5 provenance / CG-6 governance floor** — ENHANCE: reuse W2d card standard, existing signing (G12/attestation), existing constitution/allowlist. Provenance is an additive signed record, not new infra.

## §4 Smarter — mostly NET-NEW capabilities, but reuse existing rails
- SM-1..SM-5 are largely NOT in code today (no PM module, no comm autopilot) → NET-NEW capabilities.
- BUT each must ride existing rails: A6 deadline engine (reuse), C1 pre-send/UPL gate (reuse — do NOT build a new privilege gate), S5 passport (exists — extend), S2v2 shadow-associate (queued — SM-5 QA is the same shadow lane, not a second one). Frame SM-* as new features on existing gates.

## §5 Apparently pre-launch proving — ENHANCE existing harnesses (they exist!)
- ALREADY EXIST: `golden-set-runner.ts`, `golden-set-evaluator.ts`, `golden-set-ci-gate.ts`, `promo-e2e-test-harness.ts`. Do NOT build a new test framework.
- **AP-1 full-lifecycle harness** — ENHANCE promo-e2e-test-harness to cover onboarding→repo→requirements→draft→deadline→submit→renewal.
- **AP-2 golden regression** — ALREADY EXISTS (golden-set-*). Task = expand corpus coverage only.
- **AP-3 fuzz/fault injection** — NET-NEW cases added to the EXISTING harness.
- **AP-4 examiner-panel validation** — ENHANCE: point existing CADE roster (skeptical-examiner persona) at R2; reuse, don't rebuild.

## §6 Persona Test-Bot Swarm — NET-NEW (confirmed: no synthetic-persona fleet exists)
- Confirmed absent (agent_market.py, presettlement_sim.py, growth_colosseum.py are unrelated). TB-1..TB-6 are genuinely NET-NEW orchestrator infrastructure — build as specified.
- BUT reuse where possible: RICE intake via existing prompt_factory (TB-3), incident→guard via existing G11 (TB-4), scheduling via existing scheduled-tasks (TB-5), signing via existing attestation (TB-6). The fleet is new; its plumbing is not.

## Net classification
- **NET-NEW (build):** P-4 proof-lineage field, B-4 event fabric (thin), CG-2 fitness layer, CG-3 adversarial self-play, most SM-1..SM-5 features, AP-3 fuzz cases, entire §6 test-bot fleet.
- **ENHANCE/COMPLETE (extend existing, do NOT rebuild):** P-1/P-2/P-3/P-5/P-6, calibration flywheel write-back, all of §2 except B-4, CG-1/CG-4/CG-5/CG-6, AP-1/AP-2/AP-4, all SM rails.
- **ALREADY QUEUED (enhance the existing backlog item, don't add a duplicate):** B9 composite-payoff-compiler, B11 instrument-discovery-loop, S2v2 shadow-associate, HANDOFF §3.4 calibration, HANDOFF §6.2 roster cache.

Planner: drop/merge any already-decomposed v5 task that duplicates the above; re-frame ENHANCE items against their named modules. This reconciliation is the source of truth for v5 scope.
