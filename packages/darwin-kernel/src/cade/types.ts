/**
 * CADE — Consensus & Adversarial Determination Engine.
 *
 * The universal "is this the strongest defensible answer?" layer, shared by
 * tomorrow, smarter, apparently and pareto. The kernel owns the STRUCTURE and the
 * MATH (relevance matching, panel optimization, faction clustering, convergence,
 * the optimality certificate and the signed proof pack). Each product injects the
 * model-backed pieces (persona invocation, embeddings, retrieval) via adapters, so
 * this module stays pure and zero-dependency.
 *
 * Vocabulary: a *determination* is the engine's answer to one *contestable unit*
 * (a clause, an ROI, a loan rate, an insurance trigger, a feature decision). The
 * engine is *recursive*: a persona's technical sub-question is just another
 * determination one level down (the Expert-Council layer).
 */

/** Sparse competence/relevance vector: domain tag -> weight in [0,1]. */
export type CompetenceVector = Record<string, number>;

export type IssueKind =
  | 'legal'
  | 'financial'
  | 'loan'
  | 'insurance'
  | 'feature'
  | 'technical'
  | 'negotiation';

/** What a persona is here to do. */
export type PersonaRole =
  | 'authority'   // a named legal/financial mind (Tier-A roster)
  | 'discipline'  // a cross-disciplinary mosaic voice (game theory, physics, ...)
  | 'advisor'     // a technical expert seated on a council (recursive layer)
  | 'adversary'   // red team — paid to break the determination
  | 'advocate'    // Advocacy Guild — packaging/delivery (firewalled from substance)
  | 'reviewer';   // Tribunal Model — forecasts the actual decision-maker

export interface Persona {
  id: string;
  name: string;
  role: PersonaRole;
  /** What this mind is competent in (grounded in their real corpus). */
  competence: CompetenceVector;
  /** Standing authority weight in [0,1]. */
  authority: number;
  /** Learned reliability from the calibration flywheel in [0,1]. */
  reliability: number;
  /** School-of-thought / prior tag — diversity must live here, not in facts. */
  priorsTag?: string;
  /** Seated via the exploration ("productive heretic") quota. */
  exploration?: boolean;
}

export interface IssueSpec {
  id: string;
  text: string;
  kind: IssueKind;
  /** Competence the issue demands — drives the relevance gate. */
  requiredCompetence: CompetenceVector;
  /** [0,1] — drives the cost tier (panel size, rounds, recursion depth). */
  materiality: number;
  /** Audited authority class the standing roster must cover, e.g. 'scotus'. */
  rosterClass?: string;
  /** Optional pre-computed Monte Carlo distribution the panel argues over. */
  distribution?: Distribution;
}

/** A sampled quantitative distribution (finance/loan/insurance). */
export interface Distribution {
  samples: number[];
  /** Convenience percentiles, filled by summarizeDistribution. */
  p5?: number;
  p50?: number;
  p95?: number;
  tailMean?: number;
}

/** A persona's grounded position on an issue. */
export interface PersonaPosition {
  personaId: string;
  /** Scalar stance for clustering on numeric issues; text-only for legal. */
  stance: number;
  text: string;
  confidence: number; // [0,1]
  /** Argument embedding (for diversity + faction clustering). */
  embedding: number[];
  /** Real corpus citations — an assertion without one should not be made. */
  citations: string[];
  /** Sub-questions this persona wants a council to resolve (recursion seeds). */
  subQuestions?: IssueSpec[];
}

export interface Faction {
  id: string;
  memberIds: string[];
  centroid: number[];
  /** Sum of (confidence × reliability) of members. */
  support: number;
  positionSummary: string;
  /** If this faction is a synthesis, the factions it evolved from. */
  evolvedFrom?: string[];
}

export interface RedTeamHit {
  id: string;
  severity: 'minor' | 'material' | 'fatal';
  claim: string;
  byPersonaId: string;
  rebutted: boolean;
  forcedRevision: boolean;
  /** Set when the hit is a false-analogy flag. */
  falseAnalogy?: boolean;
}

/** The bounded-completeness guarantee handed to the customer. */
export interface OptimalityCertificate {
  /** Audited: the roster provably covers the required authority class. */
  rosterComplete: boolean;
  rosterClass?: string;
  /** How many minds were considered (relevance-filtered roster). */
  consideredCount: number;
  /** How many were seated for deep deliberation. */
  seatedCount: number;
  /** Bound on the best EXCLUDED mind's expected contribution (the ε). */
  marginalValueBound: number;
  confidence: number;
  /** Adding more minds stopped moving the answer. */
  saturated: boolean;
  /** Every surviving position had its strongest opponent seated. */
  adversariallyComplete: boolean;
  statement: string;
}

export interface ProofPack {
  id: string;            // content-addressed
  issueId: string;
  digest: string;        // sha256 over the canonical record
  signature?: string;    // optional Ed25519 over the digest
  publicKeyPem?: string;
  record: ProofRecord;
}

export interface ProofRecord {
  issue: IssueSpec;
  consideredPersonaIds: string[];
  excludedPersonaIds: string[];
  seatedPersonaIds: string[];
  rounds: number;
  factions: Faction[];
  redTeam: RedTeamHit[];
  distribution?: Distribution;
  certificate: OptimalityCertificate;
  /** Recursive sub-determinations (Expert-Council findings). */
  councils?: ProofPack[];
  reviewerModel?: ReviewerModel;
  createdAt: string;
}

/** Tribunal Model output. */
export interface ReviewerModel {
  known: boolean;
  /** EV-optimal vs minimax-robust posture chosen by the caller. */
  posture: 'expected_value' | 'minimax_robust';
  reviewers: { id: string; weight: number; preferenceTags: string[] }[];
  appealRobust: boolean;
}

export interface Determination {
  issueId: string;
  /** The decided position text. */
  position: string;
  /** Numeric answer when the issue is quantitative. */
  value?: number;
  confidence: number;
  /** Preserved losing factions — "the arguments opposing counsel will make". */
  dissent: Faction[];
  factions: Faction[];
  certificate: OptimalityCertificate;
  proof: ProofPack;
  /** True when the panel could not converge — honest escalation signal. */
  unsettled: boolean;
}

// ----- adapters injected by each product (keep the kernel pure) -----

export interface Invoker {
  /**
   * Run one persona against the issue at a tier. `context` carries the prior
   * round's strongest counterarguments (debate) or the parent question (council).
   */
  invoke(
    persona: Persona,
    issue: IssueSpec,
    tier: 'cheap' | 'deep',
    context?: InvokeContext,
  ): Promise<PersonaPosition>;
}

export interface InvokeContext {
  counterArguments?: string[];
  parentIssueId?: string;
  round?: number;
}

export interface Embedder {
  embed(text: string): number[];
}

export interface CadeOptions {
  /** Relevance threshold for the competence gate. */
  relevanceThreshold?: number;
  /** Diversity vs quality trade-off in panel selection, [0,1]. */
  diversityWeight?: number;
  /** Marginal-coverage stop threshold (also the certificate ε). */
  infoGainStop?: number;
  /** Fraction of seats reserved for productive-heretic exploration. */
  hereticQuota?: number;
  /** Max debate rounds. */
  maxRounds?: number;
  /** Max recursion depth for Expert Councils. */
  maxDepth?: number;
  /** Convergence threshold (JS divergence between round distributions). */
  convergenceEpsilon?: number;
  /** EV-optimal vs minimax-robust posture forwarded to the Tribunal Model. */
  posture?: ReviewerModel['posture'];
  /** Sign the proof pack via the kernel's shared Ed25519 anchor. */
  sign?: boolean;
  /** Deterministic clock for tests. */
  now?: () => string;
  /** Default posture for the reviewer model */
  posture?: 'expected_value' | 'minimax_robust';
}

export const DEFAULT_OPTIONS: Required<Omit<CadeOptions, 'sign' | 'now'>> = {
  relevanceThreshold: 0.12,
  diversityWeight: 0.5,
  infoGainStop: 0.08,
  hereticQuota: 0.08,
  maxRounds: 4,
  maxDepth: 2,
  convergenceEpsilon: 0.05,
  posture: 'expected_value',
};
