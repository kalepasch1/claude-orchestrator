/**
 * EXPERIMENTAL fleetAdmin modules — speculative until there is real production traffic.
 *
 * These are exported from the main index (the Orchestrator endpoints reference them), but they
 * are explicitly NOT part of the trusted core. They model network/market/federation dynamics
 * that only become meaningful once multiple apps + orgs are emitting real decisions. Treat their
 * outputs as directional, not authoritative, and do NOT let any of them gate a live action until
 * validated against real data.
 *
 * The TRUSTED CORE (safe to rely on now): types, autonomy, constitution, govern, plane, adapter,
 * bridge, ledger, precedent, deliberation, correlate, kpi, promotionValue, dossier, replay,
 * blastSimulator, approverModel, constitutionVerifier, executorRuntime, evalHarness, shared.
 *
 * EXPERIMENTAL (validate before trusting):
 *   - ruleMarket / shadowAB      : constitution selection by backtest — needs labeled volume
 *   - bounty                     : incentivized gap market — needs real finders + payout policy
 *   - trustWeb                   : cross-org counter-signatures — needs real counterpart orgs
 *   - marketplace / marketEconomics : two-sided artifact market — needs publishers + installers
 *   - federation                 : multi-plane mutual aid — needs ≥2 independent planes
 *   - decisionModel              : learned policy — validate via evalHarness on held-out data first
 *   - treatmentEffect            : DiD causal estimate — needs pre/post natural experiments
 *   - intentPlanner              : learned intent composition — needs a corpus of successful intents
 *   - worldModel                 : pre-launch projection — only as good as the expected-mix input
 *
 * Re-exported here purely to make the boundary explicit in one place.
 */
export * as ruleMarket from './ruleMarket.ts';
export * as shadowAB from './shadowAB.ts';
export * as bounty from './bounty.ts';
export * as trustWeb from './trustWeb.ts';
export * as marketplace from './marketplace.ts';
export * as marketEconomics from './marketEconomics.ts';
export * as federation from './federation.ts';
export * as decisionModel from './decisionModel.ts';
export * as treatmentEffect from './treatmentEffect.ts';
export * as intentPlanner from './intentPlanner.ts';
export * as worldModel from './worldModel.ts';
