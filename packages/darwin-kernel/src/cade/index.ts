/**
 * CADE — Consensus & Adversarial Determination Engine.
 *
 * The universal, recursive "strongest defensible answer" layer shared by tomorrow,
 * smarter, apparently and pareto. Pure + zero-dependency: the kernel owns the
 * structure and the math; products inject persona invocation + embeddings.
 *
 *   relevance gate (competence) → standing-roster pass → recursive Expert Councils →
 *   conclave panel optimization → blinded debate → emergent factions → convergence →
 *   adversarial red team → Tribunal Model → firewalled Advocacy Guild →
 *   optimality certificate + signed proof pack.
 */
export * from './types.ts';
export { relevance, filterByCompetence, type FilterResult } from './competence.ts';
export { selectPanel, ensureOpposition, type Candidate, type PanelSelection } from './conclave.ts';
export {
  clusterFactions,
  factionDistribution,
  jsDivergence,
  jackknifeRobust,
  hasConverged,
  synthesisSeed,
} from './factions.ts';
export { buildCertificate, buildProofPack, type CertificateInputs } from './certificate.ts';
export { packageForReviewer, type DeliveryPackage, type PackageDeps } from './advocacy.ts';
export { runDetermination, type RunDeps } from './engine.ts';
export {
  cosine,
  competenceCosine,
  distance,
  centroid,
  hashEmbedder,
  summarize,
} from './vectors.ts';

// --- frontier: determinations → settlement / capital / assurance / loop-closure ---
export {
  toOracleReading,
  impliedOverturnProbability,
  proposeEventCompression,
  marginHaircutMultiplier,
  type OracleReading,
  type ChallengeLeg,
  type EventPosition,
  type CompressionLeg,
  type CompressionResult,
} from './settlement.ts';
export {
  machineCheck,
  updateReliabilityFromOutcome,
  precedentConcentration,
  type LogicClause,
  type MachineCheckResult,
  type OutcomeEvent,
  type PrecedentEdge,
  type ConcentrationResult,
} from './assurance.ts';
export {
  propagateAuthorityChange,
  mineInstrumentGaps,
  priceDeterminationService,
  type StoredDetermination,
  type PropagationResult,
  type LegalEventLoss,
  type InstrumentCoverage,
  type InstrumentGap,
  type ServiceTier,
  type ServicePrice,
} from './loop.ts';

// --- frontier-2: interoperability, federation, finality, capital, doctrine ---
export {
  toDeterminationCredential,
  verifyDeterminationCredential,
  determinationSignature,
  matchTemplate,
  type DeterminationCredential,
  type DeterminationTemplate,
} from './credential.ts';
export {
  federatedDetermination,
  screenOracleSources,
  type LocalDetermination,
  type FederatedResult,
  type OracleSourceReading,
  type OracleScreen,
} from './federation.ts';
export {
  propagateFinality,
  type FinalityNode,
  type FinalityResult,
} from './finality.ts';
export {
  precedentPricingAdjustmentBps,
  optimizeCapitalTreatment,
  type CapitalPosition,
  type CapitalOptimization,
} from './capital.ts';
export {
  mineDoctrineUpdates,
  type DeterminationOutcome,
  type DoctrineProposal,
} from './doctrine.ts';
