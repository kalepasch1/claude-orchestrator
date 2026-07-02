/**
 * Marketplace economics — give governed-autonomy artifacts a PRICE SIGNAL and a QUALITY
 * GRADIENT. Publishers stake reputation on a listing and earn a revenue share when installs
 * perform well (measured by the installer's own regret ledger), and are slashed + downrated
 * when a listing causes regressions. The best refund policy in the world surfaces to the top,
 * and its author gets paid. Pure + zero-dep.
 */
export interface StakePosition {
  listingId: string;
  publisher: string;
  stakeUsd: number;
  /** publisher reputation 0..1, starts neutral */
  reputation: number;
}

export interface InstallOutcome {
  listingId: string;
  installer: string;
  /** revenue the install generated (subscription/usage share pool) */
  revenueUsd: number;
  /** did the installed artifact perform well for the installer? (from their regret ledger) */
  performedWell: boolean;
  /** regret rate the installer observed after installing (0 = flawless) */
  observedRegretRate: number;
}

export interface MarketEconomicsConfig {
  /** publisher's cut of revenue on a well-performing install */
  revenueSharePct: number;
  /** fraction of stake slashed per regressing install */
  slashPct: number;
  reputationStep: number;
}
export const DEFAULT_MARKET_ECONOMICS: MarketEconomicsConfig = { revenueSharePct: 0.3, slashPct: 0.1, reputationStep: 0.05 };

export interface PublisherSettlement {
  publisher: string;
  earningsUsd: number;
  slashedUsd: number;
  reputation: number;
  goodInstalls: number;
  badInstalls: number;
}

/**
 * Settle a round: distribute revenue share on good installs, slash stake + downrate on bad
 * ones, and rank publishers by the resulting reputation × earnings. Deterministic.
 */
export function settleMarket(
  stakes: StakePosition[],
  outcomes: InstallOutcome[],
  cfg: MarketEconomicsConfig = DEFAULT_MARKET_ECONOMICS,
): { settlements: PublisherSettlement[]; ranking: { publisher: string; score: number }[] } {
  const byListing = new Map(stakes.map((s) => [s.listingId, { ...s }]));
  const acc = new Map<string, PublisherSettlement>();
  const get = (pub: string, rep: number) =>
    acc.get(pub) ?? acc.set(pub, { publisher: pub, earningsUsd: 0, slashedUsd: 0, reputation: rep, goodInstalls: 0, badInstalls: 0 }).get(pub)!;

  for (const o of outcomes) {
    const stake = byListing.get(o.listingId);
    if (!stake) continue;
    const s = get(stake.publisher, stake.reputation);
    if (o.performedWell) {
      s.earningsUsd += Math.round(o.revenueUsd * cfg.revenueSharePct);
      s.reputation = Math.min(1, s.reputation + cfg.reputationStep);
      s.goodInstalls += 1;
    } else {
      const slash = Math.round(stake.stakeUsd * cfg.slashPct);
      s.slashedUsd += slash;
      stake.stakeUsd = Math.max(0, stake.stakeUsd - slash);
      s.reputation = Math.max(0, s.reputation - cfg.reputationStep * (1 + o.observedRegretRate));
      s.badInstalls += 1;
    }
  }

  const settlements = [...acc.values()];
  const ranking = settlements
    .map((s) => ({ publisher: s.publisher, score: Math.round(s.reputation * (s.earningsUsd - s.slashedUsd) * 100) / 100 }))
    .sort((a, b) => b.score - a.score);
  return { settlements: settlements.sort((a, b) => b.reputation - a.reputation), ranking };
}
