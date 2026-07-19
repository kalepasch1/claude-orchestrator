/**
 * @darwin/kernel/fleetAdmin — the shared substrate for the Fleet Admin Control Plane.
 *
 * One canonical admin vocabulary + a four-domain autonomy dial + the constitution
 * overlay + a signed-receipt gate + the app adapter contract + the Smarter approval
 * bridge + the escalation-learning flywheel. Consumed by the Orchestrator (control
 * plane), Smarter (approval inbox), and every app's adapter.
 */
export * from './types.ts';
export * from './autonomy.ts';
export * from './constitution.ts';
export * from './govern.ts';
export * from './adapter.ts';
export * from './bridge.ts';
export * from './ledger.ts';
export * from './plane.ts';
// Amplifiers (next 20–500×): case-based autonomy, prediction, adversarial pre-pass,
// cross-app correlation, quantified promotions, and the north-star KPI.
export * from './precedent.ts';
export * from './forecast.ts';
export * from './deliberation.ts';
export * from './correlate.ts';
export * from './promotionValue.ts';
export * from './kpi.ts';
// Amplifiers II (the next 50–200×): evidence-backed + self-hardening autonomy.
export * from './replay.ts';
export * from './blastSimulator.ts';
export * from './dossier.ts';
export * from './propagation.ts';
export * from './constitutionLearner.ts';
export * from './redTeam.ts';
export * from './approverModel.ts';
// Amplifiers III (50–200×+): the plane governs + optimizes + proves + heals ITSELF.
export * from './twin.ts';
export * from './federatedPrecedent.ts';
export * from './economicAutopilot.ts';
export * from './proofPack.ts';
export * from './nlControl.ts';
export * from './adapterHealth.ts';
// Amplifiers IV (20–500×+): the plane optimizes, reasons causally, self-selects its law,
// hardens itself adversarially, reports its own P&L, and decides subjects once.
export * from './paretoTuning.ts';
export * from './causal.ts';
export * from './ruleMarket.ts';
export * from './coevolution.ts';
export * from './treasury.ts';
export * from './dependencyQueue.ts';
// Amplifiers V (20–500×+): closed-loop, pre-launch simulation, cross-app reputation,
// conversational incident command, external attestation, and time-travel debugging.
export * from './selfPromotionCycle.ts';
export * from './worldModel.ts';
export * from './subjectReputation.ts';
export * from './incidentCommander.ts';
export * from './fleetAttestation.ts';
export * from './timeTravel.ts';
// Amplifiers VI (20–500×+): the plane becomes a product, governs intents, self-improves its
// law in production, learns from its own auto mistakes, and ships a compliance SKU.
export * from './capability.ts';
export * from './intent.ts';
export * from './shadowAB.ts';
export * from './regret.ts';
export * from './complianceSku.ts';
// Amplifiers VII (20–500×+): governed autonomy as a network good — a marketplace, learned
// intents, a portfolio objective, a real-time counterfactual, a bounty market, and a trust web.
export * from './marketplace.ts';
export * from './intentPlanner.ts';
export * from './portfolioObjective.ts';
export * from './counterfactual.ts';
export * from './bounty.ts';
export * from './trustWeb.ts';
// Amplifiers VIII (20–500×+): priced market, learned decision model, provable law, federated
// mutual aid, causal treatment effects, and a regulator co-pilot lens.
export * from './marketEconomics.ts';
export * from './decisionModel.ts';
export * from './constitutionVerifier.ts';
export * from './federation.ts';
export * from './treatmentEffect.ts';
export * from './regulatorLens.ts';
// Production hardening: shared primitives, idempotent/compensable executors, eval harness.
export * from './shared.ts';
export * from './executorRuntime.ts';
export * from './evalHarness.ts';
// Pre-action decision support: CADE signals + governance + blast + outcome value.
export * from './guidance.ts';
// Committee owner map — reconciles Python committees.py domain labels with the TS deliberation module.
export * from './committeeOwner.ts';
