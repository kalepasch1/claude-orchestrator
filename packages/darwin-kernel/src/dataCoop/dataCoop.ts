/**
 * Consent data-cooperative (improvement #4) — a user opts to let their consented,
 * privatized data improve models across products in exchange for a reward, settled
 * in one of the portfolio's three existing rewards currencies (Apparently points /
 * Hisanta sparks / Galop coins). Each consented contributor makes every product's
 * models better AND gets paid — a privacy-preserving data co-op on rails you
 * already own.
 *
 * Guarantees carried from federated/: a contribution only counts toward a payout
 * if the cohort clears the k-floor (no single member's data is ever isolated), and
 * the shared aggregate is ε-DP noised before it leaves the boundary.
 */
import type { ProductId } from '../types.ts';
import type { ClaimKind } from '../passport/passport.ts';
import { consentAllows, type ConsentGrant } from '../identity/graph.ts';
import { privatizeAggregate, type PrivacyConfig, DEFAULT_PRIVACY } from '../federated/privacy.ts';

export type RewardCurrency = 'apparently_points' | 'hisanta_sparks' | 'galop_coins';

export interface ContributionIntent {
  subject: string;
  /** which product the data is sourced from */
  from: ProductId;
  /** which product/pool consumes the aggregate */
  to: ProductId;
  scope: ClaimKind;
  /** the raw numeric contribution (never leaves un-privatized) */
  value: number;
}

export interface RewardLedgerEntry {
  subject: string;
  currency: RewardCurrency;
  amount: number;
  reason: string;
}

export interface CoopRoundResult {
  /** privatized aggregate that may leave the boundary (null if suppressed) */
  sharedValue: number | null;
  suppressed: boolean;
  cohortSize: number;
  /** reward entries for the contributors who consented + cleared the k-floor */
  rewards: RewardLedgerEntry[];
  rejected: { subject: string; reason: string }[];
}

/** Reward schedule: base reward per accepted contributor (tunable per pool). */
export interface RewardSchedule {
  currency: RewardCurrency;
  perContributor: number;
}

/**
 * Run one data-coop round: filter to consented contributors, k-anon + ε-DP the
 * aggregate, and pay each accepted contributor. Pure.
 */
export function runCoopRound(params: {
  contributions: ContributionIntent[];
  consent: ConsentGrant[];
  schedule: RewardSchedule;
  privacy?: PrivacyConfig;
  /** max contribution sensitivity for the DP mechanism */
  sensitivity?: number;
  rng?: () => number;
  asOf?: Date;
}): CoopRoundResult {
  const privacy = params.privacy ?? DEFAULT_PRIVACY;
  const accepted: ContributionIntent[] = [];
  const rejected: { subject: string; reason: string }[] = [];

  for (const c of params.contributions) {
    const ok = consentAllows(params.consent, {
      subject: c.subject,
      from: c.from,
      to: c.to,
      scope: c.scope,
      asOf: params.asOf,
    });
    if (ok) accepted.push(c);
    else rejected.push({ subject: c.subject, reason: 'no_consent' });
  }

  const cohortSize = accepted.length;
  const raw = accepted.reduce((s, c) => s + c.value, 0);
  const agg = privatizeAggregate(raw, cohortSize, params.sensitivity ?? 1, privacy, params.rng);

  // Pay only if the cohort cleared the k-floor (otherwise the aggregate is
  // suppressed and no value left the boundary, so no reward is owed).
  const rewards: RewardLedgerEntry[] = agg.suppressed
    ? []
    : accepted.map((c) => ({
        subject: c.subject,
        currency: params.schedule.currency,
        amount: params.schedule.perContributor,
        reason: `data_coop:${c.from}->${c.to}:${c.scope}`,
      }));

  return {
    sharedValue: agg.value,
    suppressed: agg.suppressed,
    cohortSize,
    rewards,
    rejected,
  };
}
