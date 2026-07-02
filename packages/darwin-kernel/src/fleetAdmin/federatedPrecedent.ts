/**
 * Federated cross-app precedent — a brand-new app onboards already-smart by borrowing
 * PRIVACY-WALLED precedent from the mature apps. We never move raw decisions between
 * apps; we share per-(domain,type) aggregate clean-rates through the kernel's DP
 * mechanism (k-anonymity + Laplace noise). "refunds under $20 are safe to auto"
 * transfers on day one instead of after 20 local cases. The moat deepens with every app.
 */
import { privatizeAggregate, seededRng, type PrivacyConfig, DEFAULT_PRIVACY } from '../federated/privacy.ts';
import type { AdminDomain, AutonomyTier } from './types.ts';

/** One app's local stats for an action-type (stays inside that app; only the agg leaves). */
export interface AppTypeStat {
  product: string;
  domain: AdminDomain;
  actionType: string;
  total: number;
  cleanApprovals: number;
}

export interface FederatedPrecedent {
  domain: AdminDomain;
  actionType: string;
  /** distinct apps contributing (the k-anonymity cohort) */
  cohortSize: number;
  /** DP-noised mean clean-rate across apps, or null if suppressed (cohort < k) */
  privatizedCleanRate: number | null;
  suppressed: boolean;
  /** the tier this shared prior SUPPORTS for a new app (advisory, clamp-only) */
  suggestedTier: AutonomyTier;
}

/**
 * Aggregate per-app stats into privacy-walled federated precedent. Deterministic when
 * a seed is given (auditable federated rounds). A single app's data can never surface:
 * cohorts below k are suppressed.
 */
export function buildFederatedPrecedent(
  stats: AppTypeStat[],
  cfg: PrivacyConfig = DEFAULT_PRIVACY,
  seed = 1,
): FederatedPrecedent[] {
  const groups = new Map<string, AppTypeStat[]>();
  for (const s of stats) {
    const k = `${s.domain}::${s.actionType}`;
    (groups.get(k) ?? groups.set(k, []).get(k)!).push(s);
  }

  const rng = seededRng(seed);
  const out: FederatedPrecedent[] = [];
  for (const [, arr] of groups) {
    const domain = arr[0]!.domain;
    const actionType = arr[0]!.actionType;
    // Mean of per-app clean-rates; sensitivity 1 (a rate is bounded [0,1]).
    const perApp = arr.filter((s) => s.total > 0).map((s) => s.cleanApprovals / s.total);
    const cohortSize = perApp.length;
    const rawMean = cohortSize ? perApp.reduce((a, b) => a + b, 0) / cohortSize : 0;
    const agg = privatizeAggregate(rawMean, cohortSize, 1, cfg, rng);
    const rate = agg.value === null ? null : Math.max(0, Math.min(1, Math.round(agg.value * 100) / 100));

    let suggestedTier: AutonomyTier = 'human';
    if (rate !== null) suggestedTier = rate >= 0.95 ? 'auto' : rate >= 0.6 ? 'co_pilot' : 'human';

    out.push({ domain, actionType, cohortSize, privatizedCleanRate: rate, suppressed: agg.suppressed, suggestedTier });
  }
  return out;
}

/**
 * Seed a NEW app's local precedent config from the federated priors: a map from
 * (domain::type) → the tier the cross-app cohort supports. Suppressed entries are
 * omitted (fail-closed — no prior means no borrowed autonomy).
 */
export function seedFromFederated(precedent: FederatedPrecedent[]): Record<string, AutonomyTier> {
  const out: Record<string, AutonomyTier> = {};
  for (const p of precedent) {
    if (p.suppressed || p.privatizedCleanRate === null) continue;
    out[`${p.domain}::${p.actionType}`] = p.suggestedTier;
  }
  return out;
}
