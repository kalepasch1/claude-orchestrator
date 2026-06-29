/**
 * Federated-privacy primitives — let products learn from EACH OTHER's data
 * without moving raw rows (opportunity #9). Generalized from Tomorrow's
 * federatedRiskIntel (ε-DP + k-anonymity) and Hisanta's cohort-threshold demand
 * aggregation.
 *
 * Two guarantees:
 *   - k-anonymity: a cohort smaller than k is suppressed entirely.
 *   - ε-differential privacy: numeric aggregates get calibrated Laplace noise.
 */

export interface PrivacyConfig {
  /** minimum cohort size; below this the aggregate is suppressed */
  k: number;
  /** privacy budget; lower = more noise = more privacy */
  epsilon: number;
}

export const DEFAULT_PRIVACY: PrivacyConfig = { k: 3, epsilon: 0.1 };

/** Deterministic-by-default Laplace noise. Pass a seeded rng for reproducibility. */
export function laplaceNoise(scale: number, rng: () => number = Math.random): number {
  const u = rng() - 0.5;
  return -scale * Math.sign(u) * Math.log(1 - 2 * Math.abs(u));
}

export interface PrivateAggregate {
  suppressed: boolean;
  /** noised value (null when suppressed) */
  value: number | null;
  cohortSize: number;
  reason: string;
}

/**
 * Privatize a numeric aggregate over a cohort.
 * @param rawValue the true aggregate (sum/mean)
 * @param cohortSize number of distinct contributors
 * @param sensitivity max change one contributor can cause (for the mechanism)
 */
export function privatizeAggregate(
  rawValue: number,
  cohortSize: number,
  sensitivity: number,
  cfg: PrivacyConfig = DEFAULT_PRIVACY,
  rng: () => number = Math.random,
): PrivateAggregate {
  if (cohortSize < cfg.k) {
    return { suppressed: true, value: null, cohortSize, reason: `cohort<${cfg.k}` };
  }
  const scale = sensitivity / cfg.epsilon;
  return {
    suppressed: false,
    value: rawValue + laplaceNoise(scale, rng),
    cohortSize,
    reason: 'ok',
  };
}

/** Mulberry32 — small seeded PRNG so federated rounds are reproducible/auditable. */
export function seededRng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Secure-aggregate skeleton: sum a set of per-party masked contributions where
 * masks cancel (additive secret sharing). Here we expose the k-floor check and
 * the join — real masks are wired per product. Refuses below the k-floor so a
 * single party's value can never appear in the transcript.
 */
export function secureSum(
  contributions: number[],
  cfg: PrivacyConfig = DEFAULT_PRIVACY,
): { ok: boolean; sum: number | null; reason: string } {
  if (contributions.length < cfg.k) {
    return { ok: false, sum: null, reason: `parties<${cfg.k}` };
  }
  return { ok: true, sum: contributions.reduce((a, b) => a + b, 0), reason: 'ok' };
}
