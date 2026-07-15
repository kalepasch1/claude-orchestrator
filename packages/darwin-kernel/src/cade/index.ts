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
